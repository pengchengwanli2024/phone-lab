"""Source inspection and matched execution receipts are independent axes."""
import re


def state(entry, receipts):
    sha=entry.get('source_sha256')
    if entry.get('integrity') is not True or not isinstance(sha,str) or re.fullmatch('[a-f0-9]{64}',sha) is None:
        return {'source':'missing','execution':'unmapped'}
    result={'source':'inspected' if entry.get('inspected') is True else 'indexed','execution':'unmapped'}
    adapter=entry.get('adapter')
    if not isinstance(adapter,str) or not adapter:return result
    result['execution']='adapter_ready'
    rank=0
    for receipt in receipts:
        matches=(receipt.get('skill_id')==entry.get('id') and receipt.get('source_sha256')==sha and receipt.get('adapter')==adapter)
        if matches and receipt.get('outcome')=='passed':
            rank=max(rank,{'local':1,'live':2}.get(receipt.get('level'),0))
    if rank:result['execution']={1:'local_verified',2:'live_verified'}[rank]
    return result
