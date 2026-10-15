"""FastAPI adapter: owned anonymous demo sessions, thread workers, validated delivery."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
import time
from typing import Literal,Optional
from uuid import UUID
from fastapi import FastAPI,WebSocket,Request,Response,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.websockets import WebSocketDisconnect
from pydantic import BaseModel,Field,ConfigDict,field_validator
from base.config import config
from base.safety import finalize

COOKIE='bankrag_owner'
Source=Literal['product','rate_table','regulation','business_rule','faq']
class QueryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=2000)
    source_filter:Optional[Source]=None
    session_id:Optional[UUID]=None
    include_trace:bool=False
    @field_validator('query')
    @classmethod
    def strip_query(cls,v):
        if not v.strip():raise ValueError('empty query')
        return v.strip()

def check_greeting(query):
    from rag_qa.core.query_classifier import QueryClassifier
    return '您好，我是银行存款业务演示客服。' if QueryClassifier.GREETING.fullmatch(query.strip()) else None

def create_app(system=None,allow_trace=False):
    @asynccontextmanager
    async def lifespan(app):
        if app.state.qa is None:
            def initialize():
                from integrated_qa import IntegratedQASystem
                return IntegratedQASystem()
            try:app.state.qa=await asyncio.to_thread(initialize)
            except Exception:app.state.qa=None
        yield
        if app.state.qa is not None:await asyncio.to_thread(app.state.qa.close)

    app=FastAPI(title='BankRAG 演示 API',version='2.0',lifespan=lifespan)
    app.state.qa=system
    app.state.gate=asyncio.Semaphore(2)
    app.state.session_locks={}
    origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://127.0.0.1:8090,http://localhost:8090').split(',') if x.strip()]
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,
        allow_methods=['GET','POST','DELETE'],allow_headers=['Content-Type','X-Session-Token'])
    def qa():
        if app.state.qa is None:raise HTTPException(503,'服务尚未就绪')
        return app.state.qa
    def owner(request):return request.headers.get('X-Session-Token') or request.cookies.get(COOKIE)
    async def authorize(sid,token):
        if not token or not await asyncio.to_thread(qa().owns_session,sid,token):
            raise HTTPException(403,'会话不属于当前访问者')
    def cookie(response,token):
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=os.getenv('BANKRAG_COOKIE_SECURE')=='1',max_age=604800)
    async def execute(req,sid,use_stream=False):
        if req.include_trace and not allow_trace:raise HTTPException(403,'诊断上下文未启用')
        lock=app.state.session_locks.setdefault(sid,asyncio.Lock())
        async with app.state.gate,lock:
            return await asyncio.to_thread(qa().query_result,req.query,req.source_filter,sid,use_stream)
    def payload(result,trace=False):
        out=result.public()
        if trace:
            out['contexts']=result.contexts
            out['diagnostics']=result.diagnostics
        return out

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request,exc):
        return JSONResponse({'answer':finalize(str(exc.detail)),'decision':'error','error_code':f'http_{exc.status_code}'},status_code=exc.status_code)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        return JSONResponse({'answer':finalize('请求参数无效，请检查文档类型、问题长度和会话标识。'),
            'decision':'error','error_code':'invalid_request'},status_code=422)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        return JSONResponse({'answer':finalize('服务暂时异常，请稍后重试。'),'decision':'error','error_code':'internal_error'},status_code=500)

    @app.get('/')
    async def index():return FileResponse(Path(__file__).parent/'static'/'index.html')

    @app.post('/api/create_session')
    async def create_session(request:Request,response:Response):
        token=owner(request) or secrets.token_urlsafe(32)
        sid=await asyncio.to_thread(qa().create_session,token)
        cookie(response,token)
        return {'session_id':sid}

    @app.get('/api/history/{session_id}')
    async def history(session_id:UUID,request:Request):
        sid=str(session_id);await authorize(sid,owner(request))
        return {'session_id':sid,'history':await asyncio.to_thread(qa().get_session_history,sid)}

    @app.delete('/api/history/{session_id}')
    async def clear(session_id:UUID,request:Request):
        sid=str(session_id);await authorize(sid,owner(request))
        await asyncio.to_thread(qa().clear_session_history,sid)
        return {'status':'success','answer':finalize('会话历史已清除。')}

    @app.post('/api/query')
    async def query(req:QueryRequest,request:Request,response:Response):
        start=time.perf_counter();token=owner(request)
        if req.session_id:
            sid=str(req.session_id);await authorize(sid,token)
        else:
            token=token or secrets.token_urlsafe(32)
            sid=await asyncio.to_thread(qa().create_session,token)
            cookie(response,token)
        result=await execute(req,sid)
        return {**payload(result,req.include_trace),'session_id':sid,'processing_time':time.perf_counter()-start}

    @app.get('/api/sources')
    async def sources():return {'sources':list(config.VALID_SOURCES)}

    @app.get('/health')
    async def health():
        checks=await asyncio.to_thread(qa().health) if app.state.qa else {'initialization':False}
        ok=bool(checks) and all(checks.values())
        return JSONResponse({'status':'healthy' if ok else 'degraded','dependencies':checks},
                            status_code=200 if ok else 503)

    @app.websocket('/api/stream')
    async def stream(ws:WebSocket):
        await ws.accept()
        try:
            if ws.headers.get('origin') and ws.headers['origin'] not in origins:raise HTTPException(403,'来源不被允许')
            while True:
                raw=await ws.receive_text()
                if len(raw)>12000:raise HTTPException(422,'请求过长')
                req=QueryRequest.model_validate_json(raw)
                if not req.session_id:raise HTTPException(403,'请先创建会话')
                sid=str(req.session_id);await authorize(sid,owner(ws))
                if req.include_trace and not allow_trace:raise HTTPException(403,'诊断上下文未启用')
                await ws.send_json({'type':'start','session_id':sid})
                # The first visible token carries the disclaimer even if generation is interrupted.
                await ws.send_json({'type':'token','token':config.DISCLAIMER+'\n\n','channel':'policy','session_id':sid})
                result=await execute(req,sid,use_stream=True)
                body=result.answer.replace(config.DISCLAIMER,'').strip()
                for i in range(0,len(body),32):
                    await ws.send_json({'type':'token','token':body[i:i+32],'channel':result.channel,'session_id':sid})
                    await asyncio.sleep(0)
                await ws.send_json({'type':'end','session_id':sid,'is_complete':True,**payload(result,req.include_trace)})
        except WebSocketDisconnect:
            pass  # Preamble was sent before generation; disconnected transports cannot receive a final frame.
        except Exception as exc:
            code=exc.status_code if isinstance(exc,HTTPException) else 422 if isinstance(exc,ValueError) else 500
            try:await ws.send_json({'type':'error','error':finalize('请求无效、无权访问或服务暂时异常。'),'error_code':f'ws_{code}'})
            except Exception:pass
            await ws.close(code=1008 if code<500 else 1011)
    return app

app=create_app(allow_trace=os.getenv('BANKRAG_ALLOW_TRACE')=='1')
if __name__=='__main__':
    import uvicorn
    uvicorn.run('app:app',host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8090')),reload=False)
