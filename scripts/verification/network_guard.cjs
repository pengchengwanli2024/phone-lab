// No external requests or connections to unrelated local services during gates.
const fs = require('node:fs');
const net = require('node:net');
const dns = require('node:dns');
const ports = process.env.VERIFY_PORTS_FILE;
const denials = process.env.VERIFY_DENIALS_FILE;
if (!ports || !denials) throw Error('Verification network registry required');
function deny() {
  fs.appendFileSync(denials, JSON.stringify({runtime: 'node', reason: 'unregistered fixture connection or external DNS'}) + '\n', {mode: 0o600});
  throw Error('verification_network_denied');
}
function loopback(host) {
  return host === 'localhost' || host === '::1' || (net.isIP(host) === 4 && host.startsWith('127.'));
}
function registered(port) {
  try { return fs.readFileSync(ports, 'utf8').trim().split('\n').some(line => JSON.parse(line).port === Number(port)); }
  catch { return false; }
}
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const values = Array.isArray(args[0]) ? args[0] : args;
  const first = values[0];
  const options = typeof first === 'object' ? first : {port: first, host: typeof values[1] === 'string' ? values[1] : 'localhost'};
  if (options.path || !loopback(options.host || 'localhost') || !registered(options.port)) deny();
  return connect.apply(this, args);
};
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  this.prependOnceListener('listening', () => {
    const address = this.address();
    if (!address || !loopback(address.address)) deny();
    fs.appendFileSync(ports, JSON.stringify({port: address.port}) + '\n', {mode: 0o600});
  });
  return listen.apply(this, args);
};
const lookup = dns.lookup;
dns.lookup = function (host, ...args) {
  if (!loopback(host)) deny();
  return lookup.call(this, host, ...args);
};
process.env.VERIFY_NODE_GUARD_ACTIVE = '1';
