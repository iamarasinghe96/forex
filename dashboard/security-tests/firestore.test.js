import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {initializeTestEnvironment,assertFails,assertSucceeds} from '@firebase/rules-unit-testing';
import {doc,setDoc,getDoc,collection,getDocs,deleteDoc} from 'firebase/firestore';

test('only operator can read PAPER/DEMO; every client write is denied',async()=>{
  if(!process.env.FIRESTORE_EMULATOR_HOST)throw new Error('Local emulator required; never run against a real project');
  const env=await initializeTestEnvironment({projectId:'demo-forex-security',firestore:{host:'127.0.0.1',port:8080,rules:await readFile('../firestore.rules','utf8')}});
  try {
    await env.clearFirestore();
    await env.withSecurityRulesDisabled(async context=>{
      const db=context.firestore();
      await setDoc(doc(db,'access/operator'),{uid:'operator'});
      for(const mode of ['PAPER','DEMO','LIVE'])await setDoc(doc(db,`modes/${mode}/events/one`),{kind:'fixture'});
    });
    const operator=env.authenticatedContext('operator').firestore();
    const stranger=env.authenticatedContext('stranger').firestore();
    const anonymous=env.unauthenticatedContext().firestore();
    for(const mode of ['PAPER','DEMO']){
      await assertSucceeds(getDoc(doc(operator,`modes/${mode}/events/one`)));
      await assertSucceeds(getDocs(collection(operator,`modes/${mode}/events`)));
      for(const db of [stranger,anonymous])await assertFails(getDoc(doc(db,`modes/${mode}/events/one`)));
      for(const db of [operator,stranger,anonymous]){
        await assertFails(setDoc(doc(db,`modes/${mode}/events/new`),{kind:'forged'}));
        await assertFails(deleteDoc(doc(db,`modes/${mode}/events/one`)));
      }
    }
    await assertFails(getDoc(doc(operator,'modes/LIVE/events/one')));
    await assertFails(getDoc(doc(operator,'access/operator')));
    await assertFails(setDoc(doc(stranger,'access/operator'),{uid:'stranger'}));
    await assertFails(setDoc(doc(operator,'controls/emergency'),{action:'flatten'}));
    await env.withSecurityRulesDisabled(async context=>deleteDoc(doc(context.firestore(),'access/operator')));
    await assertFails(getDoc(doc(operator,'modes/PAPER/events/one')));
  } finally {await env.cleanup();}
});
