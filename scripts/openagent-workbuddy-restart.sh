#!/bin/sh
# 保留安装入口；后台为独立 Python 进程，不注册 LaunchAgent。
set -eu
export WB_RESTART_SOURCE="$0"
exec python3 - "$@" <<'WB_RESTART_PY'
"""WorkBuddy 独立 Python 后台：等待完成、退出、直接调试启动及原 CDP 发送。"""
import argparse,base64,hashlib,json,os,plistlib,re,signal,socket,sqlite3,struct,subprocess,sys,time,urllib.request
from contextlib import closing
from pathlib import Path

CONFIG=Path.home()/'.workbuddy'
APP=Path('/Applications/WorkBuddy.app')
BUNDLE='com.tencent.workbuddy.mac'
WORKER=CONFIG/'wb-relaunch.py'
REQUEST=CONFIG/'wb-relaunch-message.json'
LOG=CONFIG/'logs/wb-relaunch.log'
PORT=9222
DEFAULT_MESSAGE='OpenAgent 已安装，打开新用户引导'

class RestartError(Exception):pass

def log(message):
    print(time.strftime('%H:%M:%S')+' [install] '+message,flush=True)

def write_private(path,text):
    """请求与后台源文件私有保存，消息正文仅在请求 JSON 中。"""
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w',encoding='utf-8') as f:f.write(text)
    path.chmod(0o600)

def app_pids():
    result=subprocess.run(['/usr/bin/lsappinfo','list'],capture_output=True,text=True,check=True)
    blocks=re.split(r'(?m)^\s*\d+\)\s+"',result.stdout)
    return [int(pid) for block in blocks if 'bundleID="'+BUNDLE+'"' in block for pid in re.findall(r'pid = (\d+)',block)]

def alive(pid):
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False

def related_pids():
    result=subprocess.run(['/bin/ps','-eo','pid,command'],capture_output=True,text=True,check=True)
    pids=set(app_pids())
    for line in result.stdout.splitlines():
        match=re.match(r'\s*(\d+)\s+(.*)',line)
        if match and re.search(r'WorkBuddy\.app|WorkBuddy Helper|codebuddy-headless',match[2]):pids.add(int(match[1]))
    return pids-{os.getpid()}

def quit_app():
    """沿用参考脚本匹配范围及 SIGKILL；后台自身不在应用进程匹配中。"""
    pids=related_pids()
    log('SIGKILL WorkBuddy 相关进程：'+','.join(str(p) for p in sorted(pids)))
    for pid in pids:
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    for _ in range(16):
        if not any(alive(p) for p in related_pids()):return
        time.sleep(.5)
    for pid in related_pids():
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass

def turn_status(sid):
    """只读当前任务状态，不查询消息正文或凭据。"""
    path=CONFIG/'workbuddy.db'
    if path.is_symlink() or not path.is_file():raise RestartError('TURN_STORE_UNAVAILABLE')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            row=db.execute('SELECT status FROM sessions WHERE id = ? AND deleted_at IS NULL',(sid,)).fetchone()
    except sqlite3.Error:raise RestartError('TURN_STORE_UNAVAILABLE') from None
    if not row:raise RestartError('TURN_NOT_FOUND')
    return row[0]

def wait_for_turn(request):
    """前台已经返回；后台每秒等待 completed，没有超时，失败不退出应用。"""
    sid=request['session_id']
    if not sid:return
    log('等待当前任务 completed')
    while True:
        if request['old_pid'] not in app_pids():raise RestartError('TURN_APP_CHANGED')
        state=turn_status(sid)
        if state=='completed':return
        if state not in ('working','planning','pending'):raise RestartError('TURN_NOT_COMPLETED')
        time.sleep(1)

def app_executable():
    with (APP/'Contents/Info.plist').open('rb') as f:name=plistlib.load(f)['CFBundleExecutable']
    exe=APP/'Contents/MacOS'/name
    if not exe.is_file() or not os.access(exe,os.X_OK):raise RestartError('APP_EXECUTABLE_UNAVAILABLE')
    return exe

def verify_trust():
    """仅核验安装程序已登记的固定来源信任；不读取 MCP 正文或自动授予其他来源信任。"""
    path=CONFIG/'mcp-approvals.json'
    if path.is_symlink():raise RestartError('TRUST_FILE_SYMLINK')
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):raise RestartError('TRUST_NOT_VERIFIED') from None
    key=hashlib.sha256(b'https://oasn-ow.haimawan.com').hexdigest()+'::openagent'
    stamp=data.get(key) if isinstance(data,dict) else None
    if type(stamp) is not int or stamp<=0:raise RestartError('TRUST_NOT_VERIFIED')

def start_app(executable):
    """直接启动二进制并显式传调试变量，不经 open 或用户 LaunchAgent。"""
    env={**os.environ,'WORKBUDDY_REMOTE_DEBUGGING_PORT':str(PORT)}
    # 任务进程可将 Electron 当 Node 运行；GUI 启动不能继承该模式或脚本注入参数。
    for key in ('ELECTRON_RUN_AS_NODE','NODE_OPTIONS','NODE_REPL_EXTERNAL_MODULE'):
        env.pop(key,None)
    log('GUI 启动环境已清理 Node 模式变量')
    child=subprocess.Popen([str(executable)],env=env,cwd=str(Path.home()),stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           start_new_session=True,close_fds=True)
    log('直接启动 WorkBuddy PID='+str(child.pid)+'，调试端口='+str(PORT))
    return child

class CDP:
    """标准库实现本机 CDP 通信；保留 60 秒等待及原有错误语义。"""
    def __init__(self,ws):
        hostport,self.path=ws[5:].split('/',1);self.path='/'+self.path
        h,p=hostport.split(':');self.sock=socket.create_connection((h,int(p)),timeout=10)
        key=base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n'%(self.path,h,p,key)).encode())
        buf=b''
        while b'\r\n\r\n' not in buf: buf+=self.sock.recv(4096)
        if b'101' not in buf.split(b'\r\n')[0]: raise RuntimeError('WS handshake failed')
        self._id=0
    def _send(self,o):
        d=json.dumps(o).encode();h=bytearray([0x81]);n=len(d);m=os.urandom(4)
        if n<126:h.append(0x80|n)
        elif n<65536:h.append(0x80|126);h+=struct.pack('>H',n)
        else:h.append(0x80|127);h+=struct.pack('>Q',n)
        h+=m;self.sock.sendall(bytes(h)+bytes(b^m[i%4] for i,b in enumerate(d)))
    def _recv(self):
        def rn(n):
            b=b''
            while len(b)<n:
                c=self.sock.recv(n-len(b))
                if not c:raise RuntimeError('CDP closed')
                b+=c
            return b
        b0,b1=rn(2);ln=b1&0x7F
        if ln==126:ln=struct.unpack('>H',rn(2))[0]
        elif ln==127:ln=struct.unpack('>Q',rn(8))[0]
        pl=rn(ln)
        if b1&0x80:mm=pl[:4];pl=bytes(c^mm[i%4] for i,c in enumerate(pl[4:]))
        return b0&0x0F,pl
    def call(self,method,params=None,timeout=60):
        self._id+=1;mid=self._id;self._send({'id':mid,'method':method,'params':params or {}})
        self.sock.settimeout(timeout)
        while True:
            op,pl=self._recv()
            if op==0x8:raise RuntimeError('CDP closed')
            if op not in (0x1,0x2):continue
            m=json.loads(pl.decode())
            if m.get('id')==mid:
                if 'error' in m:raise RuntimeError('%s: %s'%(method,m['error']))
                return m.get('result',{})
    def evaluate(self,expr,await_promise=True):
        r=self.call('Runtime.evaluate',{'expression':expr,'awaitPromise':await_promise,'returnByValue':True,'userGesture':True})
        if r.get('exceptionDetails'):raise RuntimeError('JS exception')
        return r.get('result',{}).get('value')
    def close(self):
        try:self.sock.close()
        except:pass

def find_wb():
    for _ in range(80):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list'%PORT,timeout=3) as r:
                pages=[t for t in json.loads(r.read().decode()) if t.get('type')=='page']
        except:pages=[]
        for t in pages:
            ws=t.get('webSocketDebuggerUrl')
            if not ws:continue
            try:
                c=CDP(ws)
                if c.evaluate('typeof globalThis.wb')=='object':return c
                c.close()
            except:pass
        time.sleep(0.5)
    return None

def send_message(request):
    """通过输入状态和发送 API 提交一次消息，确认创建后导航；未知结果不补发。"""
    message=request['message']
    log('等待 CDP 端口 %d …'%PORT)
    for i in range(80):
        try:
            s=socket.create_connection(('127.0.0.1',PORT),timeout=2);s.close()
            log('TCP 端口已连通');break
        except:time.sleep(0.5)
    else:
        log('[!] CDP 端口 40 秒超时');sys.exit(1)
    log('查找 wb 渲染页 …')
    c=find_wb()
    if not c:
        log('[!] 未找到 wb 渲染页');sys.exit(1)
    log('已连接 wb 渲染页')

    try:
        r=c.evaluate('(async()=>{try{await wb.connectors.setCustomMcpServerEnabled("openagent",true);return "ok";}catch(e){return "err:"+(e&&e.message);}})()')
        log('启用 openagent: %s'%r)
        r=c.evaluate('(async()=>{try{await wb.navigation.goto({tab:"home"});return "ok";}catch(e){return "err:"+(e&&e.message);}})()')
        log('goto home: %s'%r)
        time.sleep(1.4)

        # 临时捕获本次输入对应的创建结果，不依赖列表顺序或历史标题。
        WATCH_JS=r'''(message=>{const api=wb.conversations;const original=api.create;const state={id:null,pending:false,api,original};const wrapped=async function(params){const text=(params.promptContentBlocks||[]).filter(b=>b.type==='text').map(b=>b.text||'').join('');const matches=text.trim()===message.trim();if(matches)state.pending=true;try{const result=await original.call(this,params);if(matches&&result?.info?.id)state.id=result.info.id;return result;}finally{if(matches)state.pending=false;}};state.wrapped=wrapped;globalThis.__wbRestartCreated=state;api.create=wrapped;return api.create===wrapped;})'''
        if not c.evaluate(WATCH_JS+'('+json.dumps(message)+')'):
            raise RestartError('无法捕获新会话，停止发送')
        # prepareInput 等待状态应用；随后在同一 JS 执行中核对草稿并冻结发送。
        # React provider 属于宿主内部实现，无法确认唯一首页 store 时停止，不模拟操作兜底。
        SEND_JS=r'''(async message=>{
            await wb.conversations.prepareInput({target:{type:"new"},contentBlocks:[{type:"text",text:message}]});
            const stores=new Set();
            for(const el of document.querySelectorAll('textarea,[contenteditable=""],[contenteditable="true"]')){
                const rect=el.getBoundingClientRect();
                if(el.offsetParent===null||rect.width<=120||rect.height<16)continue;
                const key=Object.keys(el).find(k=>k.startsWith('__reactFiber$'));
                for(let fiber=el[key];fiber;fiber=fiber.return){
                    const props=fiber.memoizedProps;
                    const store=props?.store??props?.value;
                    if(typeof store?.api?.send==='function'&&typeof store.getSnapshot==='function'){
                        stores.add(store);break;
                    }
                }
            }
            if(stores.size!==1)return {ok:false,reason:"input-store-not-unique"};
            const store=[...stores][0],snapshot=store.getSnapshot(),draft=snapshot.draft;
            if(!draft?.sessionId?.startsWith('__home__:'))return {ok:false,reason:"input-target-changed"};
            const blocks=draft.content.blocks;
            if(draft.references.length||blocks.some(b=>b.type!=='text')||blocks.map(b=>b.text??'').join('')!==message)
                return {ok:false,reason:"input-draft-changed"};
            if(snapshot.status.disabled||snapshot.status.hostDisabled||snapshot.status.phase!=='idle'||
               draft.content.hasProcessingContent||!snapshot.capabilities.sendWired)
                return {ok:false,reason:"input-not-ready"};
            const result=await store.api.send();
            return {ok:result?.ok===true};
        })'''
        sent=c.evaluate(SEND_JS+'('+json.dumps(message)+')')
        if not sent or not sent.get('ok'):
            raise RestartError('SEND_API_NOT_CONFIRMED')
        log('发送 API 已确认提交')

        # 创建确认与导航独立于编辑器占位文本；发送结果不明时不补发。
        target_id=None
        for _ in range(60):
            target_id=c.evaluate('globalThis.__wbRestartCreated.id')
            if target_id:break
            time.sleep(0.5)
        if not target_id:
            log('[!] 未确认新会话，停止；不补发消息')
            return
        time.sleep(1)  # 让首页完成启动消息交接，再切换视图。
        log('本次新会话已创建: '+target_id)
        for _ in range(3):
            c.evaluate('(async()=>{await wb.navigation.goto({tab:"conversation",path:'+json.dumps(target_id)+'});return true;})()')
            for _ in range(12):
                time.sleep(0.25)
                if c.evaluate('wb.conversations.currentId')==target_id:
                    log('[OK] 已切换到本次新会话')
                    return
        log('[!] 新会话已创建，但界面跳转未确认；不补发消息')
    finally:
        try:
            c.evaluate('(()=>{const s=globalThis.__wbRestartCreated;if(s){if(s.api.create===s.wrapped)s.api.create=s.original;delete globalThis.__wbRestartCreated;}})()')
        finally:
            c.close()

def worker():
    """独立会话后台忽略 SIGHUP，异常清理正文；不改变或解除宿主权限。"""
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    try:
        request=json.loads(REQUEST.read_text())
        log('Python 后台开始 PID='+str(os.getpid()))
        wait_for_turn(request)
        if request['session_id'] and request['old_pid'] not in app_pids():raise RestartError('TURN_APP_CHANGED')
        exe=app_executable()
        quit_app()
        for _ in range(80):
            if not request['old_pid'] or not alive(request['old_pid']):break
            time.sleep(.5)
        time.sleep(2)
        if request['old_pid'] and alive(request['old_pid']):raise RestartError('OLD_PROCESS_STILL_ALIVE')
        log('旧实例已退出')
        start_app(exe)
        send_message(request)
        log('流程结束')
    finally:
        REQUEST.unlink(missing_ok=True)

def launch(args):
    """验证当前任务后生成纯 Python 后台文件；返回 PID 仅说明成功创建子进程。"""
    if not args.require_existing_trust:raise RestartError('EXISTING_TRUST_PROTOCOL_REQUIRED')
    message=json.loads(Path(args.message_file).read_text())['message'] if args.message_file else args.message
    if not isinstance(message,str) or not message.strip():raise RestartError('EMPTY_MESSAGE')
    sid=os.environ.get('CODEBUDDY_SESSION_ID','')
    if sid or args.wait_for_turn:
        if not re.fullmatch(r'[0-9a-f-]{36}',sid):raise RestartError('TURN_CONTEXT_REQUIRED')
        if turn_status(sid) not in ('working','planning','pending'):raise RestartError('TURN_NOT_ACTIVE')
    old=next(iter(app_pids()),0)
    if sid and not old:raise RestartError('TURN_APP_IDENTITY_UNAVAILABLE')
    app_executable()
    # 已有目录只读取；重复 mkdir 也可能触发宿主对日志目录的写入审批。
    for directory in (CONFIG,LOG.parent):
        if not directory.is_dir():directory.mkdir(parents=True,exist_ok=True)
    verify_trust();log('已核验已有固定来源信任：openagent')
    source=Path(os.environ['WB_RESTART_SOURCE']).read_text()
    source=source.split("<<'WB_RESTART_PY'\n",1)[1].rsplit('\nWB_RESTART_PY',1)[0]
    write_private(WORKER,source)
    write_private(REQUEST,json.dumps({'message':message,'session_id':sid,'old_pid':old}))
    try:
        with os.fdopen(os.open(LOG,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600),'a') as output:
            LOG.chmod(0o600)
            child=subprocess.Popen([sys.executable,str(WORKER),'--worker'],stdin=subprocess.DEVNULL,
                                   stdout=output,stderr=subprocess.STDOUT,cwd=str(Path.home()),
                                   start_new_session=True,close_fds=True)
    except Exception:
        REQUEST.unlink(missing_ok=True);raise
    log('已创建独立 Python 后台 PID='+str(child.pid)+'（尚未验证存活或重启）')
    log('全程日志：'+str(LOG))
    log('当前任务完成后由后台重启；请结束当前回复' if sid else '后台将直接重启')

def main():
    if sys.argv[1:]==['--worker']:worker();return
    parser=argparse.ArgumentParser(description='独立 Python 后台重启 WorkBuddy')
    parser.add_argument('mode',choices=['install','help'],nargs='?',default='help')
    parser.add_argument('--server',choices=['openagent'],default='openagent')
    parser.add_argument('--message-file')
    parser.add_argument('--message',default=DEFAULT_MESSAGE)
    parser.add_argument('--wait-for-turn',action='store_true')
    parser.add_argument('--require-existing-trust',action='store_true',help='要求已有固定来源信任，不自动读取 MCP 或登记信任')
    args=parser.parse_args()
    if args.mode=='help':parser.print_help();return
    launch(args)

if __name__=='__main__':
    try:main()
    except RestartError as error:log(str(error));sys.exit(1)
    except PermissionError:
        log('权限不足，请通过 WorkBuddy 原生授权处理；结果未确认时不要重复重启或发送。');sys.exit(1)
    except Exception as error:log('执行失败：'+type(error).__name__);sys.exit(1)

WB_RESTART_PY
