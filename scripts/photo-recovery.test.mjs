import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parsePhotoReference,photoHash} from '../apps/web/src/photoRecovery.ts';

test('Recovery reference excludes image bytes, filename and arbitrary stored fields',()=>{
  const reference={schema:1,key:'synthetic-upload-key',hash:'a'.repeat(64)};
  assert.deepEqual(parsePhotoReference(JSON.stringify({...reference,filename:'private.png',image:'private-data'})),reference);
});

test('Malformed or unsupported recovery references cannot become pending uploads',()=>{
  for(const raw of ['{','null',JSON.stringify({schema:2,key:'abcdefgh',hash:'a'.repeat(64)}),JSON.stringify({schema:1,key:'../bad/key',hash:'a'.repeat(64)}),JSON.stringify({schema:1,key:'abcdefgh',hash:'not-a-hash'})])assert.throws(()=>parsePhotoReference(raw));
});

test('File fingerprint is stable for identical bytes and distinguishes changed content',async()=>{
  assert.equal(await photoHash(new Blob(['abc'])),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.notEqual(await photoHash(new Blob(['abc'])),await photoHash(new Blob(['abcd'])));
});
