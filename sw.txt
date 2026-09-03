const BUILD_ID="2026.09.03.7.9";
const CACHE = "my-training-shell-"+BUILD_ID;
const CORE = ["./index.html","./manifest.json"];
const OPTIONAL = ["./apple-touch-icon.png","./icon-192.png","./icon-512.png"];

self.addEventListener("install", event => {
  event.waitUntil((async()=>{
    const cache=await caches.open(CACHE);
    await cache.addAll(CORE);
    await Promise.allSettled(OPTIONAL.map(x=>cache.add(x)));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function timeout(ms){
  return new Promise((_,reject)=>setTimeout(()=>reject(new Error("timeout")),ms));
}

self.addEventListener("fetch", event => {
  const req=event.request;
  if(req.method!=="GET")return;
  const url=new URL(req.url);
  if(url.origin!==self.location.origin)return;

  if(req.mode==="navigate"){
    event.respondWith((async()=>{
      const cached=await caches.match("./index.html");
      try{
        const response=await Promise.race([fetch(req),timeout(1500)]);
        if(response&&response.ok){
          const copy=response.clone();
          caches.open(CACHE).then(cache=>cache.put("./index.html",copy));
        }
        return response;
      }catch(e){
        if(cached)return cached;
        return new Response("Aplikacija trenutno nije dostupna.",{status:503,headers:{"Content-Type":"text/plain;charset=utf-8"}});
      }
    })());
    return;
  }

  event.respondWith(
    caches.match(req).then(cached=>{
      const network=fetch(req).then(response=>{
        if(response&&response.ok){
          const copy=response.clone();
          caches.open(CACHE).then(cache=>cache.put(req,copy));
        }
        return response;
      }).catch(()=>cached);
      return cached||network;
    })
  );
});
