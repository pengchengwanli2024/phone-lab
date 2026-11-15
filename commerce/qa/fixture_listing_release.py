"""QA-only synthetic transport with production persistence and projections."""
import copy,base64
from listing_release import ListingReleases
from test_listing_release import IMPORT,PRODUCT


class SyntheticReleaseReads(ListingReleases):
    def credentials(self,r):
        assert r['data']['synthetic']is True
        config=self.live.config()
        assert config['ozon_client_id']=='123456'
        return config
    def image(self,request_id,expected_request_sha256,index):
        from listing_review_media import descriptor
        r=self.request(request_id)
        if r['sha256']!=expected_request_sha256:raise ValueError('listing_review_request_changed')
        assert r['data']['synthetic']is True
        _,_,path=descriptor(self,r,index);path.parent.mkdir(exist_ok=True,mode=0o700)
        if not path.exists():
            path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='));path.chmod(0o600)
        return super().image(request_id,expected_request_sha256,index)


def install(app):
    tracker=SyntheticReleaseReads(app);tracker.synthetic_pending=True
    def reader(path,body,*args):
        assert args[0]=='123456'
        if path.endswith('/import/info'):
            result=copy.deepcopy(IMPORT)
            if tracker.synthetic_pending:result['result']['items'][0]['product_id']=0;tracker.synthetic_pending=False
        else:result=copy.deepcopy(PRODUCT)
        return result,'a'*64
    tracker.reader=reader;app.listing_releases=tracker
