/** Opaque host documents cannot use the authenticated HTTP device endpoints. */
export function requiresPhoneBrowser(protocol: string): boolean {
  return protocol !== 'http:' && protocol !== 'https:';
}
