# Recover a known failed original-image read

Use this procedure for registered public CDN image URLs when the original
direct read has a known failure. It was exercised on Ozon product images and
YiwuGo supplier thumbnails. It does not establish access to an entire platform,
authenticated pages, anti-bot challenges, image rights, or physical product identity.

1. Read the current dossier and exact source entry/revision/SHA. Retain the
   original failed capture receipt. If the earlier write result is UNKNOWN,
   query that upload/source first; do not begin another upload blindly.
2. Reuse the exact registered public HTTPS URL. Check its actual host against
   the intended platform CDN; do not invent a replacement URL. Do not attach shop
   credentials, cookies or authorization headers. Do not follow redirects or
   handle login/CAPTCHA challenges. Do not change the system's proxy configuration.
3. A normal HTTPS client may use the computer's already configured transport.
   Preserve TLS verification. Bound the read to the existing evidence-media
   `MAX_IMAGE` (currently 5 MiB) plus one detection byte and a finite timeout.
   Require HTTP 200; stop on HTML/challenge content or unsupported data.
4. Detect PNG/JPEG/WebP by file magic using `product_evidence_media.mime`, not
   URL suffix or the declared Content-Type. A `.jpg` URL returned valid WebP in
   the exercised path. Save the original bytes privately with the detected suffix
   and their whole-file SHA. Do not re-encode or enhance the evidence image.
5. Call the existing `commerce_product_evidence_upload_begin/chunk/finish` for
   the same case and source, with the current entry SHA, exact source URL,
   original role, actual byte size/SHA and stable upload identity. Read the
   final source back and compare URL, media ID, SHA and source revision.
6. Preserve the initial direct failure, the successful transport type, actual
   source URL and raw-file SHA. A successful upload is local evidence storage;
   the source remains unreviewed and supplies no publishing approval.

This is an agent-executed recovery method. The companion registered read-only
inspection skill does not run arbitrary Python or automatically download images.
For independent unattended recovery, use an explicitly integrated and tested
transport adapter rather than treating this document as a newly installed executor.
