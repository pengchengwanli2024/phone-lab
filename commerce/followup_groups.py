"""Read projections over original receipts; group acknowledgment is revision-bound."""
import hashlib
from agent_runtime.policy import canonical
from attention import object_json

COLUMNS='id,kind,ref,demo,revision,updated,target,receipt'


class ReceiptGroups:
    @staticmethod
    def key(row):
        target=object_json(row['target'])
        return hashlib.sha256(canonical([row['kind'],row['ref'],row['demo'],target['binding']]).encode()).hexdigest()

    def collect(self,db,kind=None,ref=None,demo=None):
        sql='SELECT '+COLUMNS+" FROM followups WHERE state='checked'";args=[]
        for name,value in (('kind',kind),('ref',ref),('demo',demo)):
            if value is not None:sql+=' AND '+name+'=?';args.append(value)
        groups={}
        for raw in db.execute(sql+' ORDER BY updated,id',args):
            row=dict(zip(COLUMNS.split(','),raw));key=self.key(row)
            groups.setdefault(key,[]).append(row)
        return groups

    @staticmethod
    def public(rows):
        latest=rows[-1];receipt=object_json(latest['receipt'])
        version=hashlib.sha256(canonical(sorted((r['id'],r['revision'])for r in rows)).encode()).hexdigest()
        return {'count':len(rows),'sha256':version,'latest':{'id':latest['id'],'checked_at':receipt['checked_at'],'condition':receipt['condition']}}
