"""Image DNS recovery never permits private targets, redirects or ambient auth."""
import json,socket,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog_media as media

class CatalogMediaNetworkTests(unittest.TestCase):
    def addr(self,*values):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(v,443))for v in values]
    def test_normal_public_address_stays_pinned_without_resolver_network(self):
        with patch.object(media.socket,'getaddrinfo',return_value=self.addr('1.1.1.1')),patch.object(media,'doh_addresses')as doh:
            self.assertEqual(media.image_addresses('images.example.com'),['1.1.1.1']);doh.assert_not_called()
    def test_only_fake_ip_vendor_cdn_uses_public_tls_dns(self):
        with patch.object(media.socket,'getaddrinfo',return_value=self.addr('198.18.0.4')),patch.object(media,'doh_addresses',return_value=['1.1.1.1'])as doh:
            self.assertEqual(media.image_addresses('ir-20.ozonstatic.cn'),['1.1.1.1']);doh.assert_called_once()
            for host in ('localhost','foo.local','images.example.com','ozonstatic.cn.attacker.example'):
                with self.assertRaisesRegex(ValueError,'catalog_image_address_rejected'):media.image_addresses(host)
    def test_private_mixed_or_reserved_answers_always_fail_closed(self):
        for addresses in [('127.0.0.1',),('192.168.1.10',),('169.254.169.254',),('1.1.1.1','127.0.0.1'),('1.1.1.1','198.18.0.4')]:
            with patch.object(media.socket,'getaddrinfo',return_value=self.addr(*addresses)),patch.object(media,'doh_addresses')as doh:
                with self.assertRaisesRegex(ValueError,'catalog_image_address_rejected'):media.image_addresses('ir-20.ozonstatic.cn')
                doh.assert_not_called()
    def test_resolver_validates_response_and_never_follows_redirects(self):
        for status,payload in [(302,{}),(200,{'Status':2}),(200,{'Status':0,'Answer':[{'type':1,'data':'127.0.0.1'}]}),(200,{'Status':0,'Answer':[]})]:
            connection=MagicMock();response=connection.getresponse.return_value;response.status=status;response.read.return_value=json.dumps(payload).encode()
            with patch.object(media,'PublicImageConnection',return_value=connection):
                with self.assertRaisesRegex(ValueError,'catalog_image_dns_'):media.doh_addresses('ir-20.ozonstatic.cn')
            connection.close.assert_called_once()
    def test_verified_public_dns_results_pin_tls_to_the_original_image_host(self):
        connection=MagicMock();response=connection.getresponse.return_value;response.status=200;response.getheader.return_value=None;response.read.return_value=b'\xff\xd8\xffsynthetic-image'
        with patch.object(media,'image_addresses',return_value=['1.1.1.1']),patch.object(media,'PublicImageConnection',return_value=connection)as make:
            raw=media.fetch('https://ir-20.ozonstatic.cn/source/photo.jpg?a=1')
        self.assertTrue(raw.startswith(b'\xff\xd8\xff'));make.assert_called_once_with('ir-20.ozonstatic.cn','1.1.1.1')
        args,kwargs=connection.request.call_args;self.assertEqual(args[:2],('GET','/source/photo.jpg?a=1'))
        self.assertFalse(set(k.lower()for k in kwargs['headers'])&{'authorization','cookie','client-id','api-key'})

    def test_lovart_generated_image_recovers_fake_dns_with_pinned_credential_free_get(self):
        connection=MagicMock();response=connection.getresponse.return_value;response.status=200;response.getheader.return_value=None
        image=b'\x89PNG\r\n\x1a\nsynthetic-image';response.read.return_value=image
        with patch.object(media.socket,'getaddrinfo',return_value=self.addr('198.18.0.4')),patch.object(media,'doh_addresses',return_value=['1.1.1.1']),patch.object(media,'PublicImageConnection',return_value=connection)as make:
            try:raw=media.fetch('https://a.lovart.ai/artifacts/generator/synthetic.png')
            except ValueError as exc:self.fail('Known generated product image could not be read: '+str(exc))
            self.assertEqual(raw,image)
        make.assert_called_once_with('a.lovart.ai','1.1.1.1')
        args,kwargs=connection.request.call_args;self.assertEqual(args[:2],('GET','/artifacts/generator/synthetic.png'))
        self.assertFalse(set(k.lower()for k in kwargs['headers'])&{'authorization','cookie','client-id','api-key'})

    def test_lovart_fake_dns_recovery_does_not_expand_to_other_paths_or_hosts(self):
        urls=['https://a.lovart.ai/artifacts/user/synthetic.png','https://a.lovart.ai/private/synthetic.png',
              'https://a.lovart.ai/artifacts/generator/../private.png','https://a.lovart.ai/artifacts/generator/synthetic.png?x=1',
              'https://a.lovart.ai/artifacts/generator/synthetic.png#fragment','https://a.lovart.ai.attacker.example/artifacts/generator/synthetic.png',
              'https://lovart.ai/artifacts/generator/synthetic.png']
        with patch.object(media.socket,'getaddrinfo',return_value=self.addr('198.18.0.4')),patch.object(media,'doh_addresses')as doh,patch.object(media,'PublicImageConnection')as make:
            for url in urls:
                with self.subTest(url=url),self.assertRaisesRegex(ValueError,'catalog_image_(address|url)_rejected'):media.fetch(url)
            doh.assert_not_called();make.assert_not_called()

    def test_lovart_private_or_mixed_dns_never_connects(self):
        for addresses in [('127.0.0.1',),('192.168.1.10',),('1.1.1.1','198.18.0.4'),('198.18.0.4','127.0.0.1')]:
            with patch.object(media.socket,'getaddrinfo',return_value=self.addr(*addresses)),patch.object(media,'doh_addresses')as doh,patch.object(media,'PublicImageConnection')as make:
                with self.assertRaisesRegex(ValueError,'catalog_image_address_rejected'):media.fetch('https://a.lovart.ai/artifacts/generator/synthetic.png')
                doh.assert_not_called();make.assert_not_called()

if __name__=='__main__':unittest.main()
