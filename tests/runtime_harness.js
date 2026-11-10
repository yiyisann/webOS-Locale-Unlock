// Deterministic offline execution of the actual runtime, including its child worker.
// Native RPC, files, HTTP, processes and clocks are all replaced. No network I/O.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {EventEmitter} = require('node:events');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/webos_locale/runtime.js'), 'utf8');
const clone = x => JSON.parse(JSON.stringify(x));

function fixture() {
    return {uid: 0, device: {modelName: 'SYNTHETIC-MODEL', firmwareVersion: '00.00.01', sdkVersion: '0.0.1'},
        locale: {locales: {UI: 'fr-FR', STT: 'fr-FR', TV: 'fr-FR', FMT: 'fr-FR'}, keyboards: ['fr'], clock: 'locale', extension: {retain: true}},
        nvram: 'SYNTHETIC-AREA', factory: 'SYNTHETIC-AREA', config: {syntheticBroadcast: 'UNCHANGED'},
        region: {country: 'SYNTHETIC', localeCountryGroup: 'syntheticGroup'},
        hbc: {returnValue: true, root: true, failsafe: false}, hbcVersion: '0.0.1',
        startupHash: crypto.createHash('sha256').update('synthetic-startup').digest('hex'), initHooks: []};
}

function environment(options = {}) {
    let now = 0, jobs = [], counter = 0, id = 0;
    const baseline = fixture(); baseline.mirror = {localeInfo: clone(baseline.locale)};
    const state = {locale: clone(baseline.locale), events: [], writes: [], commands: {id: 0, action: 'idle'},
        offline: false, stopped: false, children: [], rpc: [], config: clone(baseline.config)};
    const C = {host: '10.23.45.67', port: 9999, token: 'SYNTHETIC_CALLBACK_TOKEN', operation: options.operation || 'apply',
        target: 'zh-Hans-CN', baseline, restoreLocale: options.restoreLocale || null, allowSTT: options.allowSTT !== false,
        visualSeconds: 30, configNames: ['syntheticBroadcast']};
    function schedule(fn, delay, owner, interval) { jobs.push({at: now + (delay || 0), id: ++counter, fn, owner, interval}); }
    function pump(predicate, duration = 100000) {
        const end = now + duration;
        for (let loops = 0; loops < 100000; loops++) {
            if (predicate()) return;
            jobs.sort((a,b) => a.at - b.at || a.id - b.id);
            const job = jobs.shift();
            if (!job || job.at > end) throw Error('Synthetic deadline exceeded; events=' + JSON.stringify(state.events.map(e => [e.name, e.data.code])));
            now = job.at;
            if (job.owner && job.owner.dead) continue;
            job.fn();
            if (job.interval && !(job.owner && job.owner.dead)) schedule(job.fn, job.interval, job.owner, job.interval);
        }
        throw Error('Synthetic scheduler runaway');
    }
    function has(name) { return state.events.some(e => e.name === name); }
    function command(action) { state.commands = {id: ++id, action}; }
    function native(uri, body) {
        state.rpc.push({uri, body: clone(body)});
        if (uri.endsWith('/setSystemSettings')) {
            assert.deepEqual(Object.keys(body), ['settings']);
            assert.deepEqual(Object.keys(body.settings), ['localeInfo']);
            const desired = clone(body.settings.localeInfo); state.writes.push(clone(desired));
            const target = desired.locales.UI === C.target;
            if (target && options.reject) return {returnValue: false, errorCode: -1};
            state.locale = desired;
            if (target) {
                state.locale.locales.STT = C.target;
                if (options.unexpected) state.locale.clock = 'SYNTHETIC_UNEXPECTED';
            }
            return {returnValue: true};
        }
        if (uri.endsWith('/getSystemSettings')) return {returnValue: true, settings: body.keys && body.keys.includes('localeInfo') ? {localeInfo: clone(state.locale)} : clone(baseline.region)};
        if (uri.endsWith('/getSystemInfo')) return {returnValue: true, ...baseline.device};
        if (uri.endsWith('/getData')) return {returnValue: true, dbgroups: [{items: {contiArea2All: baseline.nvram}}]};
        if (uri.endsWith('/getFactoryOpt')) return {returnValue: true, contiArea2All: baseline.factory};
        if (uri.endsWith('/getConfigs')) return {returnValue: true, configs: clone(state.config)};
        if (uri.endsWith('/getConfiguration')) return clone(baseline.hbc);
        if (uri.endsWith('/getSystemSettingValues')) return {returnValue: true, locale: [{countries: [{spec: 'fr-FR'}]}]};
        throw Error('Unexpected native method: ' + uri);
    }
    const fakeFs = {
        readFileSync(path) {
            if (path === '/var/luna/preferences/localeInfo') return JSON.stringify({localeInfo: state.locale});
            if (path === '/etc/palm/locale.json') return JSON.stringify({locale: [{countries: [{spec: C.target}]}]});
            if (path.endsWith('locale-map.json')) return JSON.stringify({locales: {[C.target]: {synthetic: true}}});
            if (path.endsWith('appinfo.json')) return JSON.stringify({version: baseline.hbcVersion});
            if (path === '/var/lib/webosbrew/startup.sh') return 'synthetic-startup';
            throw Error('Unexpected file read: ' + path);
        }, existsSync: () => true, readdirSync: () => []
    };
    const parent = new EventEmitter(); parent.pid = 400; parent.ppid = options.parent || 1; parent.getuid = () => 0;
    parent.exit = () => {parent.dead = true; state.stopped = true;};
    const fakeCp = {
        spawnSync(path, args) {
            assert.equal(path, '/usr/bin/luna-send');
            return {status: 0, stdout: JSON.stringify(native(args[4], JSON.parse(args[5]))), stderr: ''};
        },
        spawn(path, args, spawnOptions) {
            assert.equal(path, '/usr/bin/node');
            const child = new EventEmitter(); child.pid = 401 + state.children.length; child.connected = false;
            state.children.push(child);
            let childProcess;
            child.kill = () => {
                child.dead = true; child.connected = false;
                if (childProcess) childProcess.dead = true;
                schedule(() => child.emit('exit', null, 'SIGKILL'), 0, parent);
            };
            if (spawnOptions.stdio !== 'ignore') {
                child.connected = true;
                childProcess = new EventEmitter(); childProcess.pid = child.pid; childProcess.ppid = parent.pid;
                childProcess.getuid = () => 0; childProcess.connected = true;
                childProcess.kill = (pid, signal) => {assert.equal(pid, parent.pid); assert.equal(signal, 0); assert.ok(!parent.dead);};
                childProcess.send = m => schedule(() => child.emit('message', clone(m)), 0, child);
                child.send = m => schedule(() => childProcess.emit('message', clone(m)), 0, childProcess);
                childProcess.exit = () => {
                    childProcess.dead = child.dead = true; child.connected = false;
                    schedule(() => child.emit('exit', 0, null), 0, parent);
                };
                schedule(() => {
                    if (options.workerCrash) childProcess.exit();
                    else vm.runInNewContext(args[1], context(childProcess));
                }, 0, child);
            }
            return child;
        }
    };
    const fakeHttp = {request(opts, receive) {
        const req = new EventEmitter(); req.setTimeout = () => {};
        req.destroy = error => req.emit('error', error);
        req.end = bytes => schedule(() => {
            if (state.offline || (options.noRequestAck && bytes && JSON.parse(bytes).name === 'write-request')) {
                req.emit('error', Error('SYNTHETIC_OFFLINE')); return;
            }
            const res = new EventEmitter(); res.statusCode = 200; receive(res);
            if (opts.method === 'POST') {
                const record = JSON.parse(bytes);
                if (!state.events.some(e => e.seq === record.seq)) state.events.push(record);
                res.emit('data', Buffer.from(options.falseRequestAck && record.name === 'write-request' ? '{"persisted":false}' : '{"persisted":true}'));
            } else res.emit('data', Buffer.from(JSON.stringify(state.commands)));
            res.emit('end');
        }, 0, parent);
        return req;
    }};
    function context(process) {
        class Clock extends Date {constructor(...args) {super(...(args.length ? args : [now]));} static now() {return now;}}
        return {require(name) {
            if (name === 'fs') return fakeFs;
            if (name === 'crypto') return crypto;
            if (name === 'child_process') return fakeCp;
            if (name === 'http') return fakeHttp;
            throw Error('Unexpected require');
        }, process, Buffer, Date: Clock,
        setTimeout: (fn, ms) => schedule(fn, ms, process),
        setInterval: (fn, ms) => schedule(fn, ms, process, ms)};
    }
    vm.runInNewContext(source.replace('__CONFIG__', JSON.stringify(C)), context(parent));
    function prepare() {pump(() => has('ready')); command('probe'); pump(() => has('probe-passed'));}
    return {state, C, pump, has, command, prepare};
}

let scenarios = 0;
function test(name, fn) {fn(); scenarios++; console.log('PASS ' + name);}
test('audit performs no preference writes', () => {
    const e = environment({operation: 'audit'}); e.pump(() => e.state.stopped);
    assert.ok(e.has('audit')); assert.equal(e.state.writes.length, 0);
});
test('write rejected before independent recovery rehearsal', () => {
    const e = environment(); e.pump(() => e.has('ready')); e.command('apply'); e.pump(() => e.has('error'));
    assert.equal(e.state.writes.length, 0);
});
test('probe kills child, restores complete original, then UI-only request and ordered evidence', () => {
    const e = environment(); e.prepare();
    assert.deepEqual(e.state.writes, [e.C.baseline.locale]);
    assert.equal(e.state.events.find(x => x.name === 'probe-exited').data.signal, 'SIGKILL');
    e.command('apply'); e.pump(() => e.has('verified'));
    const requested = e.state.writes[1];
    assert.equal(requested.locales.UI, 'zh-Hans-CN'); assert.equal(requested.locales.STT, 'fr-FR');
    assert.equal(e.state.locale.locales.STT, 'zh-Hans-CN');
    const order = e.state.events.filter(x => ['write-request','write-response','immediate-read','delayed-read','decision','verified'].includes(x.name)).map(x => x.name);
    assert.deepEqual(order, ['write-request','write-response','immediate-read','delayed-read','decision','verified']);
    e.command('accept'); e.pump(() => e.has('accepted')); e.command('finish'); e.pump(() => e.state.stopped);
    assert.equal(e.state.writes.length, 2);
});
for (const option of ['reject', 'unexpected', 'workerCrash']) test(option + ' causes complete original rollback', () => {
    const e = environment({[option]: true}); e.prepare(); e.command('apply'); e.pump(() => e.has('rolled-back'));
    assert.deepEqual(e.state.locale, e.C.baseline.locale); assert.ok(!e.has('accepted'));
});
test('STT linkage without opt-in causes rollback', () => {
    const e = environment({allowSTT: false}); e.prepare(); e.command('apply'); e.pump(() => e.has('rolled-back'));
    assert.deepEqual(e.state.locale, e.C.baseline.locale);
});
test('loss of controller restores without controller acknowledgement', () => {
    const e = environment(); e.prepare(); e.command('apply'); e.pump(() => e.has('verified'));
    e.state.offline = true; e.pump(() => e.state.writes.length === 3);
    assert.deepEqual(e.state.locale, e.C.baseline.locale);
});
test('visual confirmation timeout restores even while controller responds', () => {
    const e = environment(); e.prepare(); e.command('apply'); e.pump(() => e.has('verified'));
    e.pump(() => e.has('rolled-back'));
    assert.deepEqual(e.state.locale, e.C.baseline.locale);
});
test('missing durable request acknowledgement prevents target write', () => {
    const e = environment({noRequestAck: true}); e.prepare(); e.command('apply');
    e.pump(() => e.state.writes.length === 2);
    assert.ok(e.state.writes.every(w => JSON.stringify(w) === JSON.stringify(e.C.baseline.locale)));
});
test('HTTP success without durability acknowledgement also prevents target write', () => {
    const e = environment({falseRequestAck: true}); e.prepare(); e.command('apply');
    e.pump(() => e.state.writes.length === 2);
    assert.ok(e.state.writes.every(w => JSON.stringify(w) === JSON.stringify(e.C.baseline.locale)));
});
test('duplicate apply cannot issue second target write', () => {
    const e = environment(); e.prepare(); e.command('apply'); e.pump(() => e.has('verified'));
    e.command('apply'); e.pump(() => e.has('rolled-back'));
    assert.equal(e.state.writes.filter(w => w.locales.UI === e.C.target).length, 1);
});
test('explicit restore reuses full non-Japanese saved object', () => {
    const original = fixture().locale;
    const e = environment({operation: 'restore', restoreLocale: original}); e.prepare();
    e.command('apply'); e.pump(() => e.has('verified'));
    assert.deepEqual(e.state.locale, original);
});
test('protected-field drift is reported, never repaired, with bounded recovery', () => {
    const e = environment(); e.prepare(); e.command('apply'); e.pump(() => e.has('verified'));
    e.state.config.syntheticBroadcast = 'SYNTHETIC_EXTERNAL_CHANGE';
    e.pump(() => e.state.stopped);
    assert.equal(e.state.events.filter(x => x.name === 'recovery-error').length, 3);
    assert.equal(e.state.writes.length, 5); // rehearsal, target, three original-value attempts
    assert.deepEqual(e.state.locale, e.C.baseline.locale);
    assert.equal(e.state.config.syntheticBroadcast, 'SYNTHETIC_EXTERNAL_CHANGE');
    assert.ok(!e.has('rolled-back')); assert.ok(!e.has('accepted'));
});
console.log(scenarios + ' offline runtime scenarios passed');
