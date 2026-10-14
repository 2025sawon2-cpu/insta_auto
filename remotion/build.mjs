import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
await build({entryPoints:[path.join(root,'editor.jsx')],bundle:true,minify:true,
  outfile:path.join(root,'../web/remotion-editor.js'),format:'iife',jsx:'automatic',
  define:{'process.env.NODE_ENV':'"production"'},legalComments:'eof'});
