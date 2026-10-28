import { cp, mkdir, readFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const root = new URL('./', import.meta.url);
const manifest = JSON.parse(await readFile(new URL('public/media/manifest.json', root), 'utf8'));
const allowed = new Set(['index.html', 'demo.css', 'refinement.css', 'demo.js', 'media/manifest.json', ...manifest.files.map(file => `media/${file}`)]);
async function checkFiles(folder, prefix='') {
  for (const entry of await readdir(folder, {withFileTypes:true})) {
    const relative = prefix + entry.name;
    if (entry.isDirectory()) await checkFiles(new URL(`${entry.name}/`, folder), relative + '/');
    else if (!entry.isFile() || !allowed.has(relative)) throw Error(`Unreviewed static asset: ${relative}`);
  }
}
await checkFiles(new URL('public/', root));
for (const file of manifest.files) {
  if (!/^[a-z0-9-]+\.(png|mp4|wav|svg)$/.test(file)) throw Error(`Invalid media filename: ${file}`);
  const content = await readFile(new URL(`public/media/${file}`, root));
  if (createHash('sha256').update(content).digest('hex') !== manifest.integrity[file]) throw Error(`Media changed; review and update its manifest hash: ${file}`);
}
await mkdir(new URL('dist/', root), { recursive: true });
await checkFiles(new URL('dist/', root));
await cp(new URL('public/', root), new URL('dist/', root), { recursive: true });
console.log('Built static Darius showcase. No environment variables or backend required.');
