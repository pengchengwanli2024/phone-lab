"""Synthetic metadata only; no actual account or marketplace transport."""
import uuid
from datetime import datetime,timezone
from research import canonical,digest
from ozon_listing_schema import project
from test_listing_schema import TREE,ATTR,VALUES


def seed(app,connection='synthetic-listing-schema'):
    parents={}
    with app.core.atomic()as db:
        for resource,raw in [('tree',TREE),('attributes',ATTR),('values',VALUES)]:
            data=project(resource,raw);data.update(response_sha256='f'*64,parent_references=parents.copy())
            kind=app.listing_schema.kind(resource,10,20,101,0);sha=digest(canonical(data));ident=uuid.uuid4().hex
            db.execute('INSERT INTO live_snapshots VALUES(?,?,?,?,?,?)',(ident,connection,kind,canonical(data),sha,datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT OR REPLACE INTO live_latest VALUES(?,?,?)',(connection,kind,ident))
            parents[kind]=sha
