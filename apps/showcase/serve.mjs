import http from 'node:http';
import { createReadStream, statSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(fileURLToPath(new URL('./public/', import.meta.url)));
const basePath = (process.env.SHOWCASE_BASE_PATH || '').replace(/\/$/, '');
if (basePath && !/^\/[a-zA-Z0-9_-]+$/.test(basePath)) throw Error('Use a single path segment for SHOWCASE_BASE_PATH');
const securityHeaders = JSON.parse(readFileSync(new URL('./vercel.json', import.meta.url), 'utf8')).headers[0].headers;
const mime = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.png':'image/png', '.svg':'image/svg+xml', '.mp4':'video/mp4', '.wav':'audio/wav', '.json':'application/json' };
http.createServer((req,res)=>{
  for (const {key,value} of securityHeaders) res.setHeader(key,value);
  let file;
  try {
    let pathname = new URL(req.url,'http://localhost').pathname;
    if (basePath) {
      if (pathname === basePath) { res.writeHead(302, {Location: basePath + '/'}).end(); return; }
      if (!pathname.startsWith(basePath + '/')) { res.writeHead(404).end(); return; }
      pathname = pathname.slice(basePath.length);
    }
    file = path.resolve(root, '.' + decodeURIComponent(pathname));
  } catch { res.writeHead(400).end(); return; }
  if (file!==root && !file.startsWith(root+path.sep)) { res.writeHead(403).end(); return; }
  if (file===root) file=path.join(root,'index.html');
  let stat; try { stat=statSync(file); if(!stat.isFile())throw Error(); } catch { res.writeHead(404).end('Not found'); return; }
  const headers={'Content-Type':mime[path.extname(file)]||'application/octet-stream','Accept-Ranges':'bytes'};
  const match=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range||'');
  if(match){const start=Number(match[1]),end=Math.min(match[2]?Number(match[2]):stat.size-1,stat.size-1);if(start>end){res.writeHead(416,{'Content-Range':`bytes */${stat.size}`}).end();return;}res.writeHead(206,{...headers,'Content-Range':`bytes ${start}-${end}/${stat.size}`,'Content-Length':end-start+1});createReadStream(file,{start,end}).pipe(res);}
  else {res.writeHead(200,{...headers,'Content-Length':stat.size});createReadStream(file).pipe(res);}
}).listen(Number(process.env.PORT||4310),'127.0.0.1',()=>console.log(`Darius demo: http://127.0.0.1:${process.env.PORT||4310}${basePath}/`));
