"""Read-only local media index over original creative and evidence domains.

No file copies, remote reads, new approvals, or account selection changes.
"""
from datetime import datetime
import json
import math
from pathlib import Path
import re

from research import canonical,digest
from product_evidence import url as evidence_url

READ_ONLY={'commerce_media_library_list'}
KINDS=('all','product_image','competitor_image','supplier_image','generated_image','video','reference_image','audio','document','other')
PRIVATE=re.compile(r'(?i)(?:/Users/|/home/|file://|[a-z]:\\|bearer\s+|sk-[a-z0-9_-]{20,}|(?:api[_-]?key|token|password|secret)\s*[=:])')


def definitions(schema,string):
    return [('commerce_media_library_list','只读本地创意素材与当前可读商品证据原图；保留来源、店铺归属与待审核状态，不复制文件、不生成或发布',
        schema({'synthetic':{'type':'boolean'},'query':{'type':'string','maxLength':200},
                'connection_id':string,'store_ref':string,'kind':{'type':'string','enum':list(KINDS)},
                'limit':{'type':'integer','minimum':1,'maximum':50},'offset':{'type':'integer','minimum':0}},['synthetic']))]


def text(value,limit=300):
    if (not isinstance(value,str)or PRIVATE.search(value)or Path(value).is_absolute()
            or value.startswith('\\\\')or any(ord(c)<32 for c in value)):return None
    return value[:limit]or None


def public_url(value):
    if not isinstance(value,str):return None
    try:return evidence_url(value,optional=True)or None
    except ValueError:return None


def number(value):
    return value if type(value)in(int,float)and math.isfinite(value)and value>=0 else None


def timestamp(value):
    if type(value)in(int,float):return value
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):return 0


class MediaLibrary:
    def __init__(self,service):self.service=service;self.core=service.core

    @staticmethod
    def _file(root,project,filename):
        root=Path(root);folder=root/project if project else root
        if (not isinstance(filename,str)or Path(filename).name!=filename or root.is_symlink()
                or folder.is_symlink()):return False
        path=folder/filename
        try:return not path.is_symlink()and path.is_file()and path.resolve().is_relative_to(folder.resolve())
        except (OSError,ValueError):return False

    def _context(self):
        accounts=self.service.ozon_accounts.listing()
        with self.core.db()as db:
            cases={r[0]:dict(id=r[0],connection=r[1],scope=json.loads(r[2]))for r in db.execute('SELECT id,connection,scope FROM org_cases')}
        return dict(accounts={r['connection_id']:r for r in accounts['accounts']},
            active_connection=next((r['connection_id']for r in accounts['accounts']if r['active']),None),cases=cases,
            readable_cases={r['id']for r in self.service.organization.cases()})

    def _binding(self,case_id,synthetic,context):
        case=context['cases'].get(case_id);scope=case['scope']if case else{}
        same_mode=case is not None and (scope.get('synthetic')is True)==synthetic
        candidate=bool(same_mode and scope.get('origin')=='research_candidate_not_inventory')
        connection=case['connection']if same_mode and not candidate else None
        account=context['accounts'].get(connection)
        known=bool(account and scope.get('platform')=='ozon'and scope.get('market')=='RU')
        identity=dict(kind='research_candidate'if candidate else'store'if known else'unassigned',
            label=text(account['label'])if known else None,account_id=account['account_id']if known else None,
            connection_id=connection,platform=scope.get('platform')if same_mode else None,
            market=scope.get('market')if same_mode else None,active=bool(known and account['active']),
            store_ref='ozon-live'if known and account['active']else None,identity_verified=False)
        return dict(case_id=case_id if same_mode else None,
            product_id=text(str(scope['product_id']))if same_mode and scope.get('product_id')is not None else None,
            sku=text(str(scope['sku']))if same_mode and scope.get('sku')is not None else None,
            product_name=text(scope.get('label'))if same_mode else None,store_identity=identity,
            product_readable=bool(same_mode and case_id in context['readable_cases']),
            binding_status='exact_case_metadata'if same_mode else'case_missing_or_mode_mismatch'if case_id else'unbound')

    @staticmethod
    def _preview(tool,args,available,reason):
        return dict(available=available,tool=tool if available else None,arguments=args if available else{},
            status=reason,validation='registered_metadata_and_file_presence_only; verify_returned_bytes_against_sha256')

    @staticmethod
    def _kind(asset_kind):
        if 'video'in asset_kind:return 'video'
        if asset_kind in ('generated_image','image_layout_draft'):return 'generated_image'
        if asset_kind=='product_image':return 'product_image'
        if asset_kind in ('reference_image','keyframe'):return 'reference_image'
        if asset_kind=='audio':return 'audio'
        if asset_kind in ('captions','production_manifest','quality_report','delivery_package','design_analysis'):return 'document'
        return 'other'

    def _creative(self,synthetic,context):
        with self.core.db()as db:
            projects={r[0]:json.loads(r[1])for r in db.execute('SELECT id,brief FROM creative_projects')}
            assets=list(db.execute('SELECT id,project,kind,metadata,filename FROM creative_assets'))
            requests=list(db.execute('SELECT id,project,document FROM creative_requests'))
        reviews={}
        for rid,project,encoded in requests:
            doc=json.loads(encoded);review=doc.get('review')or{}
            if review.get('decision')not in ('approved','rejected'):continue
            for asset in doc.get('assets',[]):
                reviews.setdefault((project,asset.get('id'),asset.get('sha256')),[]).append(dict(
                    request_id=rid,decision=review['decision'],result_sha256=doc.get('result_sha256'),
                    scope='original_request_local_review_only',current_request_revalidated=False))
        for aid,pid,asset_kind,encoded,filename in assets:
            brief=projects.get(pid)
            if brief is None or (brief.get('synthetic')is True)!=synthetic:continue
            meta=json.loads(encoded);media=meta.get('media')if isinstance(meta.get('media'),dict)else{}
            binding=brief.get('product_binding')or{};identity=self._binding(binding.get('case_id'),synthetic,context)
            project_name=text(brief.get('product',{}).get('name'));available=self._file(self.service.creative.root,pid,filename)
            records=reviews.get((pid,aid,meta.get('sha256')),[])
            kind=self._kind(asset_kind)
            yield dict(id='creative:'+aid,origin='creative',project_id=pid,project_name=project_name,
                asset_id=aid,asset_kind=asset_kind,kind=kind,role=asset_kind,source_kind=None,
                display_name=text(meta.get('display_name'))or project_name or asset_kind,
                source_url=public_url(meta.get('source_ref')),source_reference=text(meta.get('source_ref'),1000),
                sha256=meta.get('sha256'),size=number(meta.get('size')),width=number(media.get('width')),
                height=number(media.get('height')),duration_seconds=number(media.get('duration_seconds')),
                created_at=meta.get('created_at'),synthetic=synthetic,quality_verified=False,
                rendition='thumbnail'if meta.get('thumbnail')is True or meta.get('is_thumbnail')is True else'unknown',
                review_status='local_review_recorded'if records else'unreviewed',request_reviews=records,
                publication_approved=False,independently_verified=False,
                storage_status='registered_local_file'if available else'missing_local_file',
                preview=self._preview('commerce_creative_asset_read',dict(project_id=pid,asset_id=aid,offset='0'),available,
                    'registered_local_file'if available else'missing_local_file'),
                **{**identity,'product_name':identity['product_name']or project_name})

    def _evidence(self,synthetic,context,issues):
        dossier=self.service.product_evidence
        current=context['readable_cases']
        with self.core.db()as db:
            documents={r[0]:json.loads(r[1])for r in db.execute('SELECT id,document FROM product_evidence_images')}
        for cid in sorted(current):
            case=context['cases'].get(cid)
            if not case or (case['scope'].get('synthetic')is True)!=synthetic:continue
            identity=self._binding(cid,synthetic,context)
            try:groups=dossier._versions(cid)
            except ValueError:
                issues.append(dict(code='evidence_source_integrity_unavailable',case_id=cid));continue
            for entry_id,versions in groups.items():
                if entry_id=='proposal':continue
                source=dossier._view(versions)
                for index,ref in enumerate(source['images']):
                    media_id=ref['media_id'];doc=documents.get(media_id,{})
                    intact=bool(doc and doc.get('case_id')==cid and doc.get('entry_id')==entry_id
                        and doc.get('document_sha256')==digest(canonical({k:v for k,v in doc.items()if k!='document_sha256'})))
                    available=bool(intact and self._file(dossier.media.root,None,doc.get('filename')))
                    reason='source_archived'if source['archived']else'link_only'if not media_id else'registered_local_file'if available else'missing_or_invalid_local_file'
                    available=available and not source['archived']
                    role=ref['role'];source_kind=source['kind'];kind=('generated_image'if role=='generated'else'document'if role=='document'
                        else'supplier_image'if source_kind=='supplier'else'competitor_image'if source_kind=='competitor'else'reference_image')
                    media=doc.get('media')if intact and isinstance(doc.get('media'),dict)else{}
                    yield dict(id='evidence:'+digest(canonical([cid,entry_id,media_id or ref['url'],index])),origin='product_evidence',
                        project_id=None,project_name=None,asset_id=media_id or None,asset_kind='evidence_image',kind=kind,role=role,
                        entry_id=entry_id,entry_sha256=source['sha256'],entry_revision=source['revision'],image_index=index,
                        source_kind=source_kind,source_label=text(source.get('label')),source_url=public_url(ref['url']),
                        source_reference=None,display_name=text(ref.get('label'))or text(source.get('label'))or kind,
                        sha256=doc.get('sha256')if intact else None,size=number(doc.get('size'))if intact else None,
                        width=number(media.get('width')),height=number(media.get('height')),duration_seconds=number(media.get('duration_seconds')),
                        created_at=source.get('saved_at'),synthetic=synthetic,quality_verified=False,rendition='unknown',
                        review_status='unreviewed',request_reviews=[],source_review_state=source['review_state'],rights_status=source['rights_status'],
                        publication_approved=False,independently_verified=False,storage_status=reason,
                        preview=self._preview('commerce_product_evidence_image',dict(case_id=cid,entry_id=entry_id,
                            expected_entry_sha256=source['sha256'],index=index,offset=0),available,reason),**identity)

    def listing(self,synthetic,query='',connection_id=None,store_ref=None,kind='all',limit=50,offset=0):
        if (type(synthetic)is not bool or not isinstance(query,str)or len(query)>200 or kind not in KINDS
                or type(limit)is not int or not 1<=limit<=50 or type(offset)is not int or offset<0
                or any(value is not None and (not isinstance(value,str)or not 1<=len(value)<=160)for value in (connection_id,store_ref))):
            raise ValueError('media_library_invalid_filter')
        with self.service.live.config_lock:
            context=self._context();issues=[];rows=[*self._creative(synthetic,context),*self._evidence(synthetic,context,issues)]
            selected=[];facets={}
            for row in rows:
                identity=row['store_identity']
                if kind!='all'and row['kind']!=kind:continue
                if query.casefold()not in canonical([row.get(k)for k in ('display_name','project_name','product_name','sku','product_id','source_label','store_identity')]).casefold():continue
                facet_ref=identity.get('account_id')or identity.get('connection_id')or ('research_candidates'if identity['kind']=='research_candidate'else'unassigned')
                facet=facets.setdefault(facet_ref,dict(store_ref=facet_ref,label=identity['label'],
                    connection_id=identity['connection_id'],account_id=identity['account_id'],kind=identity['kind'],active=identity['active'],count=0))
                facet['count']+=1
                if connection_id and identity['connection_id']!=connection_id:continue
                if store_ref and store_ref!='all':
                    if store_ref=='unassigned':match=identity['kind']=='unassigned'
                    elif store_ref=='research_candidates':match=identity['kind']=='research_candidate'
                    elif store_ref=='ozon-live':match=bool(context['active_connection']and identity['connection_id']==context['active_connection'])
                    else:match=store_ref in (identity.get('account_id'),identity.get('connection_id'))
                    if not match:continue
                selected.append(row)
            selected.sort(key=lambda r:(timestamp(r['created_at']),r['id']),reverse=True)
            total=len(selected);page=selected[offset:offset+limit]
            return dict(schema='commerce-local-media-library-v1',synthetic=synthetic,items=page,total=total,
                offset=offset,limit=limit,next_offset=offset+len(page)if offset+len(page)<total else None,
                stores=sorted(facets.values(),key=lambda r:(not r['active'],r['kind'],r['label']or'',r['store_ref'])),
                store_facets_complete=True,store_facets_scope='matching_synthetic_query_kind_before_store_filter_and_pagination',
                kinds=list(KINDS),issues=issues[:20],issues_truncated=len(issues)>20,
                coverage=dict(creative='all_saved_local_projects',evidence='current_readable_cases_latest_sources_only',
                    inactive_evidence='not_indexed_preview_not_advertised'),
                external_execution_allowed=False,files_copied=0,new_approvals=0,
                limitations=['Metadata and file presence are indexed; preview consumers must verify returned bytes against the recorded hash.',
                    'Local review records apply to their original request, not publication or a new use.',
                    'Inactive-store evidence is not exposed through an unavailable preview contract.'])

    def invoke(self,name,args):
        if name!='commerce_media_library_list':raise ValueError('unknown_tool')
        return self.listing(**args)
