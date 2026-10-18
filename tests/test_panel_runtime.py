"""Exercise the shipped panel's boot/login/navigation with browser boundaries stubbed."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
HARNESS = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const base = process.argv[1];
const modules = {};
for (const file of ['servers', 'subscription']) {
  modules[file] = await import('data:text/javascript;base64,' +
    Buffer.from(fs.readFileSync(`${base}/web/js/${file}.js`)).toString('base64'));
}
const source = fs.readFileSync(`${base}/web/js/app.js`, 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^boot\(\).*;\s*$/m, '');
const storage = (values = new Map()) => ({
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: key => values.delete(key),
});
const profile = {email:'fixture@example.test', display_id:42, devices:[], max_devices:3};
function panel({local = storage(), tab = storage(new Map([['sv-panel-session','1']])), api = {}} = {}) {
  const node = () => ({innerHTML:'', classList:{add(){},remove(){}},
    querySelectorAll:()=>[], querySelector:()=>null});
  const app = node(), timers = [], listeners = {};
  const document = {hidden:false, visibilityState:'visible', body:node(),
    getElementById:()=>app, addEventListener:(name, fn)=>{listeners[name]=fn;}};
  const context = vm.createContext({console, document, localStorage:local,
    sessionStorage:tab, location:{hostname:'router.test'},
    window:{addEventListener:(name, fn)=>{listeners[name]=fn;},
      prompt:(msg, initial)=>(initial && String(initial).trim()) || 'Renamed', confirm:()=>true},
    setTimeout, clearTimeout, setInterval:fn=>{timers.push(fn);return timers.length;},
    clearInterval(){}, ...modules.servers, ...modules.subscription,
    palette:()=>({}), applyPalette(){}, mountToggleSnake(){}, toggleMarkup:()=>'',
    api:{status:async()=>({session:true,connected:true}), theme:async()=>({}),
      servers:async()=>({}), dns:async()=>({}), exclusions:async()=>({}),
      profile:async()=>profile, login:async()=>({profile,connected:true}),
      logout:async()=>({ok:true}), renameDevice:async()=>({}), deleteDevice:async()=>({}),
      ...api},
  });
  vm.runInContext(source + '\nglobalThis.panel={state,boot,login,logout,handle,toggleVpn};', context);
  return {...context.panel, app, timers, listeners, api:context.api, document};
}
'''


@unittest.skipUnless(NODE, "Node required for real panel runtime scenarios")
class PanelRuntimeTests(unittest.TestCase):
    def test_update_is_only_on_home_and_menu_has_close_and_back(self):
        self.run_panel('''
const p=panel({api:{updateCheck:async()=>({phase:'available',version:'1.0.170'}),updateStatus:async()=>({phase:'idle'})}});
await p.boot();await p.handle('update-check');
assert.ok(p.app.innerHTML.includes('Доступно обновление'));
assert.ok(!p.app.innerHTML.includes('dock-title'));
await p.handle('menu');assert.equal(p.state.menu,true);
assert.ok(p.app.innerHTML.includes('data-act="menu-close"'));
await p.handle('menu-close');assert.equal(p.state.menu,false);
await p.handle('page',{dataset:{page:'about'}});
assert.ok(p.app.innerHTML.includes('data-act="page-back"'));
assert.ok(!p.app.innerHTML.includes('data-act="update-start"'));
await p.handle('page-back');assert.equal(p.state.page,null);assert.equal(p.state.menu,true);
assert.ok(p.app.innerHTML.includes('data-act="update-start"'));
''')

    def test_update_button_is_in_home_dock_and_survives_temporary_restart(self):
        self.run_panel('''
const p=panel({api:{updateCheck:async()=>({phase:'available',version:'1.0.171'}),
 updateStatus:async()=>({phase:'idle'}),updateStart:async()=>({phase:'downloading',detail:'Downloading'})}});
await p.boot();await p.handle('update-check');
assert.ok(p.app.innerHTML.includes('data-act="update-start"'));
assert.ok(p.app.innerHTML.includes('1.0.171'));
await p.handle('update-start');assert.equal(p.state.update.phase,'downloading');
assert.ok(p.app.innerHTML.includes('Downloading'));
// Logout during update is blocked in the UI; call logout() directly.
await p.logout();assert.equal(p.state.session,null);
''')

    def test_about_uses_installed_version_from_router_status(self):
        self.run_panel('''
const p=panel({api:{status:async()=>({session:true,version:'1.0.171'})}});
await p.boot(); await p.handle('page',{dataset:{page:'about'}});
assert.ok(p.app.innerHTML.includes('Версия 1.0.171'));
assert.ok(p.app.innerHTML.includes('WireGuard-туннель через VK TURN/DTLS'));
assert.ok(!p.app.innerHTML.includes('Версия 1.0.170'));
assert.ok(!p.app.innerHTML.includes('WDTT'));
assert.ok(!p.app.innerHTML.includes('только панель'));
''')

    def run_panel(self, scenario):
        result = subprocess.run([NODE, "--input-type=module", "-e", HARNESS + scenario,
                                 ROOT.as_posix()], capture_output=True, text=True,
                                encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reopen_loads_account_from_boolean_router_status(self):
        self.run_panel('''
const p = panel(); await p.boot();
assert.equal(p.state.profile?.email, profile.email);
assert.ok(p.app.innerHTML.includes('fixture@example.test'));
assert.equal(p.state.connected, true);
''')

    def test_other_browser_on_lan_requires_password_even_if_router_has_session(self):
        self.run_panel('''
const p = panel({tab:storage()}); await p.boot();
assert.equal(p.state.session, null);
assert.ok(p.app.innerHTML.includes('data-act="login"'));
''')

    def test_logout_keeps_vpn_connected_flag_from_api(self):
        self.run_panel('''
const p=panel({api:{logout:async()=>({ok:true,connected:true}),
  status:async()=>({session:true,connected:true})}});
await p.boot();assert.equal(p.state.connected,true);
p.api.status=async()=>({session:false,connected:true});
await p.logout();
assert.equal(p.state.session,null);
assert.equal(p.state.connected,true);
assert.ok(p.app.innerHTML.includes('data-act="login"'));
''')

    def test_unchecked_remember_requires_login_in_new_tab_without_logout(self):
        self.run_panel('''
const local = storage(); let logouts = 0;
const api = {logout:async()=>{logouts++;return {};}};
const p = panel({local, api}); p.state.email=profile.email;
p.state.password='fixture-password'; p.state.remember=false; await p.login();
const reloaded = panel({local, tab:storage(), api}); await reloaded.boot();
assert.equal(reloaded.state.session, null);
assert.equal(logouts, 0, 'Closing a tab must leave router VPN running');
''')

    def test_devices_navigation_fetches_new_online_state(self):
        self.run_panel('''
let calls=0; const p=panel({api:{login:async()=>({profile:{...profile,
  devices:[{device_name:'Fixture',is_connected:false}]} }),profile:async()=>{
  calls++;return {...profile, devices:[{device_name:'Fixture',is_connected:true}]};
}}}); p.state.email=profile.email; p.state.password='fixture-password';await p.login();
await p.handle('page',{dataset:{page:'devices'}});
assert.equal(p.state.profile.devices[0].is_connected,true);
assert.equal(calls,1);
assert.ok(p.app.innerHTML.includes('VPN онлайн: 1'));
''')

    def test_checked_remember_prefills_credentials_after_logout_and_reopen(self):
        self.run_panel('''
const values=new Map(), local=storage(values);const p=panel({local});
p.state.email=profile.email;p.state.password='fixture-password';await p.login();
const reopened=panel({local});await reopened.boot();
assert.equal(reopened.state.profile.email,profile.email);
assert.equal(p.state.password,'');
await p.logout();
assert.equal(p.state.email,profile.email);
assert.equal(p.state.password,'fixture-password');
assert.ok(p.app.innerHTML.includes('value="fixture-password"'));
const loggedOut=panel({local,api:{status:async()=>({session:false})}});
await loggedOut.boot();assert.equal(loggedOut.state.session,null);
assert.equal(loggedOut.state.email,profile.email);
assert.equal(loggedOut.state.password,'fixture-password');
''')

    def test_unchecked_remember_clears_previous_saved_credentials(self):
        self.run_panel('''
const local=storage();const p=panel({local});
p.state.email=profile.email;p.state.password='fixture-password';await p.login();
await p.logout();p.state.remember=false;p.state.password='new-password';await p.login();
await p.logout();assert.equal(p.state.password,'');assert.equal(p.state.email,'');
const reopened=panel({local,api:{status:async()=>({session:false})}});await reopened.boot();
assert.equal(reopened.state.password,'');assert.equal(reopened.state.email,'');
''')

    def test_failed_login_does_not_replace_saved_credentials(self):
        self.run_panel('''
const local=storage();const p=panel({local});
p.state.email=profile.email;p.state.password='fixture-password';await p.login();await p.logout();
p.state.email='wrong@example.test';p.state.password='wrong-password';
p.api.login=async()=>{throw new Error('Invalid login');};await p.login();
const reopened=panel({local,api:{status:async()=>({session:false})}});await reopened.boot();
assert.equal(reopened.state.email,profile.email);assert.equal(reopened.state.password,'fixture-password');
''')

    def test_unchecked_remember_survives_reload_of_same_tab(self):
        self.run_panel('''
const local=storage(), tab=storage();const p=panel({local,tab});
p.state.email=profile.email;p.state.password='fixture-password';p.state.remember=false;await p.login();
const reloaded=panel({local,tab});await reloaded.boot();
assert.equal(reloaded.state.profile.email,profile.email);
''')

    def test_unavailable_profile_shows_retry_and_never_empty_account(self):
        self.run_panel('''
let healthy=false; const p=panel({api:{profile:async()=>healthy?profile:{detail:'Temporary failure'}}});
await p.boot();assert.equal(p.state.session,null);
assert.ok(p.app.innerHTML.includes('Повторить загрузку аккаунта'));
healthy=true;await p.handle('restore');assert.equal(p.state.profile.email,profile.email);
''')

    def test_profile_poll_preserves_last_data_on_error_and_pauses_when_hidden(self):
        self.run_panel('''
let calls=0;const p=panel({api:{profile:async()=>{calls++;
  if(calls>1)throw new Error('Offline');return profile;}}});await p.boot();
await p.handle('page',{dataset:{page:'devices'}});
assert.equal(p.state.profile.email,profile.email);
assert.ok(p.app.innerHTML.includes('Показаны последние данные'));
// Only the actual list timer runs; an idle or hidden page makes no requests.
p.state.page=null;for(const tick of p.timers)await tick();assert.equal(calls,2);
p.state.page='devices';p.document.hidden=true;
for(const tick of p.timers)await tick();assert.equal(calls,2);
''')

    def test_late_profile_does_not_restore_logged_out_account(self):
        self.run_panel('''
let resolve;const p=panel();await p.boot();
p.api.profile=()=>new Promise(done=>{resolve=done;});
const pending=p.handle('page',{dataset:{page:'devices'}});
await p.logout();resolve(profile);await pending;
assert.equal(p.state.session,null);assert.equal(p.state.profile,null);
assert.ok(p.app.innerHTML.includes('data-act="login"'));
''')

    def test_visible_list_poll_updates_online_devices_without_parallel_requests(self):
        self.run_panel('''
let calls=0, resolve;const p=panel();await p.boot();p.state.page='devices';
p.api.profile=()=>{calls++;return new Promise(done=>{resolve=done;});};
for(const tick of p.timers)tick();p.listeners.focus();
assert.equal(calls,1);
resolve({...profile,devices:[{device_name:'Fixture',is_connected:true}]});
await new Promise(done=>setImmediate(done));
assert.ok(p.app.innerHTML.includes('VPN онлайн: 1'));
''')

    def test_own_router_uses_local_connection_and_other_sessions_keep_server_state(self):
        self.run_panel('''
const p=panel({api:{status:async()=>({session:true,connected:true,device_id:'router'}),
profile:async()=>({...profile,devices:[{id:'router',device_type:'pc',is_connected:false},
  {id:'other',device_type:'pc',is_connected:false}]})}});await p.boot();
assert.equal(p.state.profile.devices[0].self,true);
assert.equal(p.state.profile.devices[0].is_connected,true);
assert.equal(p.state.profile.devices[1].is_connected,false);
p.api.status=async()=>({session:true,connected:false,device_id:'router'});
await p.handle('page',{dataset:{page:'devices'}});
assert.equal(p.state.profile.devices[0].is_connected,false);
assert.equal(p.state.connected,false);
''')

    def test_other_devices_keep_hive_online_while_router_tunnel_is_up(self):
        self.run_panel('''
const p=panel({api:{status:async()=>({session:true,connected:true,device_id:'router'}),
profile:async()=>({...profile,devices:[
  {id:'router',device_type:'pc',device_name:'OpenWrt',is_connected:false},
  {id:'phone',device_type:'android',device_name:'Android',is_connected:true},
  {id:'laptop',device_type:'pc',device_name:'PC',is_connected:true},
]})}});
await p.boot();await p.handle('page',{dataset:{page:'devices'}});
assert.equal(p.state.profile.devices[0].is_connected,true);
assert.equal(p.state.profile.devices[1].is_connected,true);
assert.equal(p.state.profile.devices[2].is_connected,true);
assert.ok(p.app.innerHTML.includes('VPN онлайн: 3'));
assert.equal((p.app.innerHTML.match(/В сети/g)||[]).length,3);
''')

    def test_slow_profile_cannot_undo_completed_vpn_toggle(self):
        self.run_panel('''
let resolve;const p=panel({api:{disconnect:async()=>({connected:false})}});await p.boot();
p.api.profile=()=>new Promise(done=>{resolve=done;});
const pending=p.handle('page',{dataset:{page:'devices'}});
await p.toggleVpn();assert.equal(p.state.connected,false);
resolve(profile);await pending;assert.equal(p.state.connected,false);
''')

    def test_devices_page_exposes_rename_and_delete_actions(self):
        self.run_panel('''
const p=panel({api:{status:async()=>({session:true,connected:true,device_id:'router'}),
  profile:async()=>({...profile,devices:[{id:'router',device_name:'OpenWrt lab',device_type:'pc',is_connected:true},
    {id:'phone',device_name:'Android',device_type:'android',is_connected:false}]})}});
await p.boot();await p.handle('page',{dataset:{page:'devices'}});
assert.ok(p.app.innerHTML.includes('data-act="device-rename"'));
assert.ok(p.app.innerHTML.includes('data-act="device-delete"'));
assert.ok(p.app.innerHTML.includes('data-id="phone"'));
let renamed=null, deleted=null;
p.api.renameDevice=async(id,name)=>{renamed={id,name};};
p.api.deleteDevice=async(id)=>{deleted=id;};
p.api.profile=async()=>({...profile,devices:[{id:'phone',device_name:'Phone',device_type:'android'}]});
await p.handle('device-rename',{dataset:{id:'phone'}});
assert.deepEqual(renamed,{id:'phone',name:'Renamed'});
await p.handle('device-delete',{dataset:{id:'phone',self:'0'}});
assert.equal(deleted,'phone');
''')

    def test_router_tokens_without_panel_flag_stay_on_login_while_vpn_up(self):
        self.run_panel('''
const p=panel({tab:storage(), api:{status:async()=>({session:true,connected:true})}});
await p.boot();
assert.equal(p.state.session,null);
assert.equal(p.state.connected,true);
assert.ok(p.app.innerHTML.includes('data-act="login"'));
assert.ok(p.app.innerHTML.includes('VPN на роутере включён'));
''')


if __name__ == "__main__":
    unittest.main()
