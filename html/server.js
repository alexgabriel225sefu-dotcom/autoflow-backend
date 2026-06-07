const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;

const mime = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  let filePath = path.join(__dirname, req.url === '/' ? 'index.html' : req.url);
  if (!path.extname(filePath)) filePath += '.html';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      fs.readFile(path.join(__dirname, 'index.html'), (e, d) => {
        res.writeHead(e ? 404 : 200, { 'Content-Type': 'text/html', 'Cache-Control': 'no-cache' });
        res.end(e ? 'Not found' : d);
      });
      return;
    }
    res.writeHead(200, { 'Content-Type': mime[path.extname(filePath)] || 'text/plain', 'Cache-Control': 'no-cache, no-store, must-revalidate' });
    res.end(data);
  });
});

server.listen(PORT, () => console.log(`AiCash System running on port ${PORT}`));
