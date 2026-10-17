const CACHE='civicsignal-shell-v2';
const SHELL='/';

self.addEventListener('install',event=>{
  event.waitUntil((async()=>{
    const cache=await caches.open(CACHE);
    const response=await fetch(SHELL);
    if(!response.ok)throw new Error('The online app shell could not be cached.');
    const html=await response.clone().text();
    await cache.put(SHELL,response);
    const assets=[...html.matchAll(/(?:src|href)="([^\"]+)"/g)].map(match=>match[1]).filter(path=>path.startsWith('/assets/'));
    if(assets.length)await cache.addAll([...new Set(assets)]);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    for(const name of await caches.keys())if(name.startsWith('civicsignal-shell-')&&name!==CACHE)await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  // Never cache authenticated API replies or account data.
  if(url.pathname.startsWith('/api/'))return;
  if(request.mode==='navigate'){
    event.respondWith((async()=>{
      try{
        const response=await fetch(request);
        if(response.ok){const cache=await caches.open(CACHE);await cache.put(SHELL,response.clone());}
        return response;
      }catch{return (await caches.match(SHELL))||Response.error();}
    })());
    return;
  }
  if(url.pathname.startsWith('/assets/')){
    event.respondWith((async()=>{
      const cache=await caches.open(CACHE);
      try{const response=await fetch(request);if(response.ok)await cache.put(request,response.clone());return response;}
      catch{return (await cache.match(request))||Response.error();}
    })());
  }
});
