const http = require('http');
const net = require('net');
const fs = require('fs');
const LOG = '/tmp/token-tracker.jsonl';
const PID_FILE = '/tmp/token-tracker.pid';

function log(entry) {
  entry.ts = new Date().toISOString();
  fs.appendFileSync(LOG, JSON.stringify(entry) + '\n');
}

const server = http.createServer(() => {});

server.on('connect', (req, clientSocket, head) => {
  const [host, port] = req.url.split(':');
  log({ event: 'connect', host, port: port || 443 });
  const srv = net.connect(port || 443, host, () => {
    clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
    srv.pipe(clientSocket);
    clientSocket.pipe(srv);
  });
  srv.on('error', () => clientSocket.end());
  clientSocket.on('error', () => srv.end());
});

server.listen(9999, () => {
  fs.writeFileSync(PID_FILE, String(process.pid));
  log({ event: 'start', pid: process.pid });
});
