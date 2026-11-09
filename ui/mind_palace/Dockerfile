FROM node:18-alpine

WORKDIR /app

COPY package.json index.html ./
COPY vendor ./vendor
COPY src ./src

EXPOSE 3000

CMD ["node", "-e", "require('http').createServer(function(req,res){var fs=require('fs');var p=decodeURIComponent(req.url.split('?')[0]);if(p==='/')p='/index.html';var f=__dirname+p;fs.readFile(f,function(e,d){if(e){res.writeHead(404);res.end('Not Found');}else{var m=p.endsWith('.html')?'text/html; charset=utf-8':p.endsWith('.js')?'application/javascript; charset=utf-8':p.endsWith('.css')?'text/css; charset=utf-8':'application/octet-stream';res.writeHead(200,{'Content-Type':m});res.end(d);}});}).listen(3000)"]
