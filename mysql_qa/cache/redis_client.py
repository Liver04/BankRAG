import json
import hashlib
from redis import StrictRedis
from base.config import config
class RedisClient:
    PREFIX='bankrag:'
    def __init__(self):
        self.redis=StrictRedis(host=config.REDIS_HOST,port=config.REDIS_PORT,db=config.REDIS_DB,password=config.REDIS_PASSWORD,
            decode_responses=True,socket_connect_timeout=3,socket_timeout=3)
    def key(self,revision,key):return f'{self.PREFIX}v2:{revision}:'+hashlib.sha256(key.encode()).hexdigest()
    def get_data(self,key,revision='v2'):
        try:
            v=self.redis.get(self.key(revision,key))
            return json.loads(v) if v else None
        except Exception:return None
    def set_data(self,key,value,revision='v2',ttl=3600):
        try:self.redis.set(self.key(revision,key),json.dumps(value,ensure_ascii=False),ex=ttl)
        except Exception:pass
    def invalidate(self):
        for key in self.redis.scan_iter(match=self.PREFIX+'*',count=100):self.redis.unlink(key)
    def health(self):return bool(self.redis.ping())
    def close(self):self.redis.close()
