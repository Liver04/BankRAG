"""Short-lived connections; atomic, versioned bank FAQ snapshots."""
from contextlib import contextmanager
import hashlib
import uuid
import unicodedata
import pymysql
from base.config import config
from base.safety import eligible,today_int,redact

def question_key(q):
    return hashlib.sha256(unicodedata.normalize('NFKC',q).strip().rstrip('？?。!！').encode()).hexdigest()

class MysqlClient:
    @contextmanager
    def connection(self):
        c=pymysql.connect(host=config.MYSQL_HOST,port=config.MYSQL_PORT,user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,database=config.MYSQL_DATABASE,charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,connect_timeout=5,read_timeout=10,write_timeout=10)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:c.close()

    def create_table(self):
        with self.connection() as c,c.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS bank_faq (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,question VARCHAR(1000) NOT NULL,answer TEXT NOT NULL,
                source VARCHAR(50) DEFAULT 'faq',category VARCHAR(50) DEFAULT '',updated_at VARCHAR(20) DEFAULT '')""")
            cur.execute('SHOW COLUMNS FROM bank_faq')
            existing={r['Field'] for r in cur.fetchall()}
            fields={'question_hash':'CHAR(64) NULL','faq_id':"VARCHAR(64) DEFAULT ''",
                'doc_id':"VARCHAR(64) DEFAULT ''",'block_id':"VARCHAR(64) DEFAULT ''",
                'title':"VARCHAR(512) DEFAULT ''",'source_url':'TEXT NULL','review_status':"VARCHAR(32) DEFAULT 'pending'",
                'effective_date':'INT DEFAULT 0','expiry_date':'INT DEFAULT 0','version':"VARCHAR(64) DEFAULT ''",
                'jurisdiction':"VARCHAR(8) DEFAULT 'CN'",'category':"VARCHAR(50) DEFAULT ''",'updated_at':"VARCHAR(20) DEFAULT ''",
                'provenance_json':'TEXT NULL'}
            for field,ddl in fields.items():
                if field not in existing:cur.execute(f'ALTER TABLE bank_faq ADD COLUMN {field} {ddl}')
            cur.execute('SELECT id,question FROM bank_faq WHERE question_hash IS NULL')
            for r in cur.fetchall():
                cur.execute('UPDATE bank_faq SET question_hash=%s WHERE id=%s',(question_key(r['question']),r['id']))
            cur.execute('DELETE a FROM bank_faq a JOIN bank_faq b ON a.question_hash=b.question_hash AND a.id<b.id')
            cur.execute('SHOW INDEX FROM bank_faq WHERE Key_name=%s',('uq_bank_question',))
            if not cur.fetchone():cur.execute('ALTER TABLE bank_faq ADD UNIQUE KEY uq_bank_question(question_hash)')
            cur.execute('CREATE TABLE IF NOT EXISTS bank_knowledge_state (name VARCHAR(32) PRIMARY KEY,version CHAR(64) NOT NULL)')
            cur.execute("INSERT IGNORE INTO bank_knowledge_state VALUES ('faq','uninitialized')")
            cur.execute("""CREATE TABLE IF NOT EXISTS bank_sessions (
                session_id CHAR(36) PRIMARY KEY,owner_hash CHAR(64) NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,session_id VARCHAR(36) NOT NULL,question TEXT NOT NULL,
                answer TEXT NOT NULL,timestamp DATETIME NOT NULL,_is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
                INDEX idx_session_id(session_id))""")

    def replace_faq(self,records,revision):
        with self.connection() as c,c.cursor() as cur:
            cur.execute("SELECT version FROM bank_knowledge_state WHERE name='faq' FOR UPDATE")
            names=['question','answer','source','category','updated_at','question_hash','faq_id','doc_id','block_id',
                'title','source_url','review_status','effective_date','expiry_date','version','jurisdiction','provenance_json']
            sql='INSERT INTO bank_faq ('+','.join(names)+') VALUES ('+','.join(['%s']*len(names))+')'
            sql+=' ON DUPLICATE KEY UPDATE '+','.join(f'{n}=VALUES({n})' for n in names if n!='question_hash')
            cur.execute('DELETE FROM bank_faq')
            for r in records:
                row=dict(r,question_hash=question_key(r['question']))
                cur.execute(sql,tuple(row.get(n,'') for n in names))
            cur.execute("UPDATE bank_knowledge_state SET version=%s WHERE name='faq'",(revision,))
        return len(records)

    def knowledge_version(self):
        with self.connection() as c,c.cursor() as cur:
            cur.execute("SELECT version FROM bank_knowledge_state WHERE name='faq'")
            r=cur.fetchone()
            return r['version'] if r else 'uninitialized'

    def fetch_eligible(self):
        now=today_int()
        with self.connection() as c,c.cursor() as cur:
            cur.execute("""SELECT * FROM bank_faq WHERE review_status='demo_approved' AND jurisdiction='CN'
                AND effective_date<=%s AND (expiry_date=0 OR expiry_date>=%s) ORDER BY question_hash""",(now,now))
            return cur.fetchall()

    def fetch_record(self,key):
        with self.connection() as c,c.cursor() as cur:
            cur.execute('SELECT * FROM bank_faq WHERE question_hash=%s',(key,))
            r=cur.fetchone()
            return r if r and eligible(r) else None

    def create_session(self,owner):
        sid=str(uuid.uuid4())
        with self.connection() as c,c.cursor() as cur:
            cur.execute('INSERT INTO bank_sessions(session_id,owner_hash) VALUES(%s,%s)',(sid,hashlib.sha256(owner.encode()).hexdigest()))
        return sid

    def owns_session(self,sid,owner):
        if not owner:return False
        with self.connection() as c,c.cursor() as cur:
            cur.execute('SELECT session_id FROM bank_sessions WHERE session_id=%s AND owner_hash=%s',(sid,hashlib.sha256(owner.encode()).hexdigest()))
            return cur.fetchone() is not None

    def history(self,sid):
        with self.connection() as c,c.cursor() as cur:
            cur.execute('SELECT question,answer FROM conversations WHERE session_id=%s AND _is_deleted=FALSE ORDER BY timestamp DESC,id DESC LIMIT 5',(sid,))
            return list(reversed(cur.fetchall()))

    def save_history(self,sid,question,answer):
        with self.connection() as c,c.cursor() as cur:
            cur.execute('INSERT INTO conversations(session_id,question,answer,timestamp) VALUES(%s,%s,%s,NOW())',(sid,redact(question),redact(answer)))

    def clear_history(self,sid):
        with self.connection() as c,c.cursor() as cur:
            cur.execute('UPDATE conversations SET _is_deleted=TRUE WHERE session_id=%s',(sid,))
        return True

    def health(self):
        with self.connection() as c,c.cursor() as cur:
            cur.execute('SELECT 1')
            return bool(cur.fetchone())
    def close(self):pass
