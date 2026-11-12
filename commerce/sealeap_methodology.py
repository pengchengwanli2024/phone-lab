"""Literal SKILL.md method index; heading heuristics are not domain acceptance."""
import hashlib
import json
import re

VERSION='literal-source-method-v2'
INPUT_HEADING=re.compile(r'开始前要拿到|开始前.*(?:输入|资料)|必要输入|任务与输入|输入|input|建立事实包|准备资料',re.I)
DELIVERY_HEADING=re.compile(r'交付|输出|output|deliverable',re.I)
PROCEDURE_HEADING=re.compile(r'工作流|工作流程|执行流程|操作步骤|判断标准|判断状态|任务模式|选择.*模式|^执行$',re.I)
BOUNDARY_HEADING=re.compile(r'边界|执行范围|使用范围|证据.*约定|guardrail',re.I)


def checksum(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def segments(entry):
    """Expose nested headings without replacing the original heading/text."""
    for index,section in enumerate(entry['sections']):
        heading=section['heading'];start=1;lines=[]
        for number,line in enumerate(section['text'].splitlines(),1):
            match=re.match(r'^#{1,6}\s+(.+)',line)
            if match:
                if any(x.strip() for x in lines):yield index,heading,start,'\n'.join(lines)
                heading=section['heading']+' / '+match.group(1);start=number+1;lines=[]
            else:lines.append(line)
        if any(x.strip() for x in lines):yield index,heading,start,'\n'.join(lines)


def units(text):
    numbered=[(i,line) for i,line in enumerate(text.splitlines(),1) if re.match(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)',line)]
    # Preserve original text. Unbulleted notes remain in the source document.
    if numbered:return numbered
    paragraphs=[];current=[];start=1
    for i,line in enumerate(text.splitlines()+[''],1):
        if not line.strip():
            if current:paragraphs.append((start,'\n'.join(current)));current=[]
        else:
            if not current:start=i
            current.append(line)
    # Navigation-only prose is not an input field or a deliverable.
    return [(i,t) for i,t in paragraphs if not re.search(r'\[[^\]]+\]\([^\)]+\)',t) or not re.match(r'^(?:详细|涉及|遇到|需要|按需|最后|先读取|.*见\s*\[)',t)]


def method_for(entry):
    roles=dict(inputs=[],deliverables=[],procedures=[],boundaries=[]);combined=[]
    source_file=next(f for f in entry['files'] if f['path']=='SKILL.md')
    for index,heading,start,text in segments(entry):
        if INPUT_HEADING.search(heading):role='inputs'
        elif DELIVERY_HEADING.search(heading):
            if re.search(r'执行与交付|交付边界',heading):combined.append((index,heading,start,text));continue
            role='deliverables'
        elif BOUNDARY_HEADING.search(heading):role='boundaries'
        elif PROCEDURE_HEADING.search(heading):role='procedures'
        else:continue
        for offset,literal in units(text):
            roles[role].append(dict(text=literal,source=dict(path='SKILL.md',file_sha256=source_file['sha256'],section_index=index,heading=heading,section_relative_line=start+offset-1)))
    if not roles['deliverables']:
        for index,heading,start,text in combined:
            for offset,literal in units(text):roles['deliverables'].append(dict(text=literal,source=dict(path='SKILL.md',file_sha256=source_file['sha256'],section_index=index,heading=heading,section_relative_line=start+offset-1),classification='combined_workflow_and_delivery_requires_review'))
    else:
        for index,heading,start,text in combined:
            for offset,literal in units(text):roles['boundaries'].append(dict(text=literal,source=dict(path='SKILL.md',file_sha256=source_file['sha256'],section_index=index,heading=heading,section_relative_line=start+offset-1)))
    supplementary=entry.get('input_sources',{})
    if not roles['inputs']:roles['inputs']=[{k:v for k,v in row.items() if k not in ['id','mode_id']} for row in supplementary.get('common',[])]
    modes=supplementary.get('modes',{})
    for role,prefix in [('inputs','I'),('deliverables','D'),('procedures','P'),('boundaries','B')]:
        for i,item in enumerate(roles[role],1):item.update(id=prefix+str(i),kind=role)
    gaps=[]
    if not roles['inputs'] and not any(m['inputs'] for m in modes.values()):gaps.append('input_heading_not_identified_read_full_workflow')
    if not roles['deliverables']:gaps.append('deliverable_heading_not_identified_read_full_workflow')
    value=dict(version=VERSION,skill_id=entry['id'],source_sha256=entry['source_sha256'],**roles,
        mode_methods=modes,mode_selection_required=supplementary.get('mode_selection_required',False),
        input_resolution='mode_scoped' if modes and not roles['inputs'] else 'common_source' if roles['inputs'] else 'unresolved',
        extraction_gaps=gaps,scope='Literal candidates from registered SKILL.md, reviewed prerequisite sources and selected-mode guides; other references are not exhaustive.',
        semantic_review='pending',reference_requirements_exhaustive=False,platform_execution=False)
    return dict(value,sha256=checksum(value))


def review_requirements(method):
    return method['inputs']+method['deliverables']


def validate_checks(method,checks,section_ids,fact_ids,reference_ids=()):
    expected={r['id']:r for r in review_requirements(method)}
    if not isinstance(checks,list) or len(checks)!=len(expected):raise ValueError('sealeap_source_requirements_missing')
    seen=set();gaps=[]
    for row in checks:
        if not isinstance(row,dict) or set(row)!={'requirement_id','status','basis_refs','section_ids','note'}:raise ValueError('sealeap_source_check_invalid')
        ident=row['requirement_id']
        if not isinstance(ident,str) or ident not in expected or ident in seen:raise ValueError('sealeap_source_check_identity_invalid')
        seen.add(ident);status=row['status'];refs=row['basis_refs'];sections=row['section_ids']
        if status not in ['covered_in_draft','partial','missing','not_applicable'] or not isinstance(row['note'],str) or not 1<=len(row['note'])<=500:raise ValueError('sealeap_source_check_invalid')
        if not isinstance(refs,list) or len(refs)>12 or any(not isinstance(v,str) or v not in set(fact_ids)|set(reference_ids) for v in refs):raise ValueError('sealeap_source_check_fact_reference_invalid')
        if not isinstance(sections,list) or len(sections)>8 or any(not isinstance(v,str) or v not in section_ids for v in sections):raise ValueError('sealeap_source_check_section_invalid')
        if expected[ident]['kind']=='inputs' and status in ['covered_in_draft','partial'] and not any(v in fact_ids for v in refs):raise ValueError('sealeap_source_input_check_evidence_required')
        if expected[ident]['kind']=='deliverables' and status in ['covered_in_draft','partial'] and not sections:raise ValueError('sealeap_source_delivery_check_section_required')
        if status in ['missing','partial']:gaps.append(ident)
    return gaps
