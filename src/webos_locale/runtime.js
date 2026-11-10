// MIT. In-memory HBC diagnostic/transaction agent; no TV files or listening ports.
(function (C) {
    'use strict';
    function helpers(config) {
        var fs = require('fs'), cp = require('child_process'), crypto = require('crypto');
        var base = 'luna://com.webos.settingsservice/';
        function copy(x) { return JSON.parse(JSON.stringify(x)); }
        function stable(x) {
            if (Array.isArray(x)) return '[' + x.map(stable).join(',') + ']';
            if (x && typeof x === 'object') return '{' + Object.keys(x).sort().map(function (k) { return JSON.stringify(k) + ':' + stable(x[k]); }).join(',') + '}';
            return JSON.stringify(x);
        }
        function same(a, b) { return stable(a) === stable(b); }
        function diff(a, b, p) {
            p = p || ''; if (same(a, b)) return [];
            if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
                var result = [];
                Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort().forEach(function (k) {
                    result = result.concat(diff(a[k], b[k], p + '/' + k.replace(/~/g, '~0').replace(/\//g, '~1')));
                }); return result;
            }
            return [{path: p, before: a === undefined ? {absent: true} : a, after: b === undefined ? {absent: true} : b}];
        }
        function rpc(uri, body) {
            var result = {uri: uri, payload: copy(body), requestJSON: JSON.stringify(body), startedUTC: new Date().toISOString()};
            var processResult = cp.spawnSync('/usr/bin/luna-send', ['-w', '3000', '-n', '1', uri, result.requestJSON], {encoding: 'utf8', timeout: 4500, maxBuffer: 800000});
            result.finishedUTC = new Date().toISOString(); result.status = processResult.status;
            result.stdout = processResult.stdout || ''; result.stderr = processResult.stderr || '';
            if (processResult.error) result.errorCode = processResult.error.code || 'NATIVE_REQUEST_FAILED';
            try { result.response = JSON.parse(result.stdout); } catch (_) {}
            return result;
        }
        function value(result) {
            if (!result.response || result.response.returnValue !== true) throw new Error('NATIVE_READ_FAILED');
            return result.response;
        }
        function locale() {
            var raw = rpc(base + 'getSystemSettings', {keys: ['localeInfo']}), result = {raw: raw, value: null};
            if (raw.response && raw.response.settings) result.value = raw.response.settings.localeInfo;
            try { result.mirror = JSON.parse(fs.readFileSync('/var/luna/preferences/localeInfo', 'utf8')); }
            catch (_) { result.mirrorError = true; }
            return result;
        }
        function snapshot() {
            var l = locale(), device = value(rpc('luna://com.webos.service.tv.systemproperty/getSystemInfo', {keys: ['modelName', 'firmwareVersion', 'sdkVersion']}));
            var s = {uid: process.getuid(), device: {modelName: device.modelName, firmwareVersion: device.firmwareVersion, sdkVersion: device.sdkVersion},
                locale: l.value, mirror: l.mirror || {}, rawLocale: l.raw};
            s.nvram = value(rpc('luna://com.webos.service.lowlevelstorage/getData', {dbgroups: [{dbid: 'factory', items: ['contiArea2All']}]})).dbgroups[0].items.contiArea2All;
            s.factory = value(rpc('luna://com.webos.service.factorymanager/getFactoryOpt', {keys: ['contiArea2All'], subscribe: false})).contiArea2All;
            s.config = value(rpc('luna://com.webos.service.config/getConfigs', {configNames: config.configNames})).configs;
            s.region = value(rpc(base + 'getSystemSettings', {category: 'option', keys: ['country', 'smartServiceCountryCode2', 'smartServiceCountryCode3', 'localeCountryGroup']})).settings;
            s.hbc = value(rpc('luna://org.webosbrew.hbchannel.service/getConfiguration', {}));
            s.hbcVersion = JSON.parse(fs.readFileSync('/media/developer/apps/usr/palm/applications/org.webosbrew.hbchannel/appinfo.json', 'utf8')).version;
            s.startupHash = crypto.createHash('sha256').update(fs.readFileSync('/var/lib/webosbrew/startup.sh')).digest('hex');
            s.initHooks = fs.readdirSync('/var/lib/webosbrew/init.d').sort();
            return s;
        }
        function audit(s) {
            var tag = config.target, definition = JSON.parse(fs.readFileSync('/etc/palm/locale.json', 'utf8'));
            var map = JSON.parse(fs.readFileSync('/usr/palm/applications/com.palm.app.settings/locale-map.json', 'utf8')).locales;
            var list = value(rpc(base + 'getSystemSettingValues', {key: 'locale'})), selectable = [];
            (list.locale || []).forEach(function (entry) { (entry.countries || []).forEach(function (c) { selectable.push(c.spec); }); });
            var tags = []; (definition.locale || []).forEach(function (entry) { (entry.countries || []).forEach(function (c) { tags.push(c.spec); }); });
            var target = {defined: tags.indexOf(tag) >= 0, settingsEntry: !!map[tag], catalogs: {}};
            // This profile's paths were verified. Other catalog layouts are not guessed.
            if (tag === 'zh-Hans-CN') {
                target.catalogs.settings = fs.existsSync('/usr/palm/applications/com.palm.app.settings/resources/zh/strings.json');
                target.catalogs.home = fs.existsSync('/usr/palm/applications/com.webos.app.home/data/flutter_assets/assets/i18n/zh.json');
                target.catalogs.quicksettings = fs.existsSync('/usr/palm/applications/com.webos.app.quicksettings/data/flutter_assets/assets/i18n/zh.json');
                target.simplifiedFont = fs.existsSync('/usr/share/fonts/LG_Smart_UI_SC.ttf');
            }
            s.audit = {selectable: selectable, definedTags: tags, target: target, requestedTag: tag};
            return s;
        }
        function expected(actual) {
            if (config.operation === 'restore') return same(actual, config.restoreLocale);
            if (!actual || !actual.locales || actual.locales.UI !== config.target) return false;
            return diff(config.baseline.locale, actual).every(function (d) {
                return (d.path === '/locales/UI' || (config.allowSTT && d.path === '/locales/STT')) && d.after === config.target;
            });
        }
        function check(s, desired) {
            var before = config.baseline;
            if (s.uid !== 0 || !s.hbc.root || s.hbc.failsafe || !same(s.locale, desired) || !same(s.mirror.localeInfo, desired)) throw new Error('LOCALE_OR_ROOT_INVARIANT_FAILED');
            ['device', 'nvram', 'factory', 'config', 'region', 'hbc', 'hbcVersion', 'startupHash', 'initHooks'].forEach(function (k) {
                if (!same(s[k], before[k])) throw new Error('PROTECTED_ENVIRONMENT_CHANGED');
            });
        }
        return {copy: copy, same: same, diff: diff, rpc: rpc, value: value, locale: locale, snapshot: snapshot, audit: audit, expected: expected, check: check, base: base};
    }
    function worker(config, H) {
        var callbacks = {}, used = false;
        process.on('message', function (m) { if (m.ack && callbacks[m.ack]) { var f = callbacks[m.ack]; delete callbacks[m.ack]; f(); } });
        function save(name, data, next) { callbacks[name] = next || function () {}; process.send({name: name, data: data}); }
        process.on('uncaughtException', function () { if (process.connected) process.send({name: 'worker-error', data: {code: 'WORKER_EXCEPTION'}}); process.exit(2); });
        var desired = config.operation === 'restore' ? H.copy(config.restoreLocale) : H.copy(config.baseline.locale);
        if (config.operation === 'apply') desired.locales.UI = config.target;
        var payload = {settings: {localeInfo: desired}};
        if (config.operation === 'apply' && !H.same(H.diff(config.baseline.locale, desired), [{path: '/locales/UI', before: config.baseline.locale.locales.UI, after: config.target}])) throw new Error('REQUEST_SCOPE_REJECTED');
        save('write-request', {uri: H.base + 'setSystemSettings', payload: payload, requestJSON: JSON.stringify(payload), workerPid: process.pid, watchdogPid: process.ppid}, function () {
            if (used) throw new Error('DUPLICATE_MUTATION'); used = true; process.kill(process.ppid, 0);
            var response = H.rpc(H.base + 'setSystemSettings', payload);
            // Preserve the raw write reply before any further potentially failing read.
            save('write-response', response, function () {
                var first = H.locale();
                save('immediate-read', {readback: first, changes: H.diff(config.baseline.locale, first.value)}, function () {
                    setTimeout(function () {
                        var last = H.locale();
                        save('delayed-read', {readback: last, changes: H.diff(config.baseline.locale, last.value)}, function () {
                            var ok = response.response && response.response.returnValue === true && H.expected(first.value) && H.expected(last.value) && first.mirror && last.mirror && H.same(first.value, first.mirror.localeInfo) && H.same(last.value, last.mirror.localeInfo);
                            save('decision', {ok: !!ok}, function () { process.exit(0); });
                        });
                    }, 650);
                });
            });
        });
    }
    var H = helpers(C), http = require('http'), cp = require('child_process');
    var sequence = 0, queue = [], posting = false, stopped = false, phase = 'starting', dirty = false, restoring = false, tested = false, used = false, recoveryExhausted = false;
    var child = null, lastId = 0, lastContact = Date.now(), start = Date.now(), trialStart = 0, visualStart = 0, lastCheck = 0;
    function request(method, path, body, callback) {
        var bytes = body ? Buffer.from(JSON.stringify(body)) : null, completed = false;
        function finish(error, data) { if (completed) return; completed = true; callback(error, data); }
        var req = http.request({host: C.host, port: C.port, path: path, method: method, headers: bytes ? {'Content-Type': 'application/json', 'Content-Length': bytes.length} : {}}, function (res) {
            var text = ''; res.on('data', function (b) { text += b; }); res.on('end', function () {
                try { if (res.statusCode !== 200) throw new Error('CALLBACK_REJECTED'); var data = JSON.parse(text); lastContact = Date.now(); finish(null, data); } catch (e) { finish(e); }
            });
        });
        req.on('error', function (e) { finish(e); }); req.setTimeout(2000, function () { req.destroy(new Error('CALLBACK_TIMEOUT')); }); req.end(bytes);
    }
    function flush() {
        if (posting || !queue.length) return; posting = true; var e = queue[0];
        request('POST', '/event/' + C.token, e.record, function (error, data) {
            posting = false; if (error || !data || data.persisted !== true) { setTimeout(flush, 300); return; }
            queue.shift(); if (e.next) e.next(); flush();
        });
    }
    function event(name, data, next) { queue.push({record: {seq: ++sequence, name: name, utc: new Date().toISOString(), data: data}, next: next}); flush(); }
    function stopChild() { if (child) { try { child.kill('SIGKILL'); } catch (_) {} child = null; } }
    function rollback(reason, rehearsal, attempt) {
        if (restoring || stopped || recoveryExhausted || (phase === 'recovery-error' && !attempt)) return; restoring = true; phase = 'restoring'; stopChild(); attempt = attempt || 1;
        var result = H.rpc(H.base + 'setSystemSettings', {settings: {localeInfo: C.baseline.locale}});
        event('recovery-write', {reason: reason, rehearsal: !!rehearsal, result: result, attempt: attempt});
        setTimeout(function () {
            var snapshot;
            try { H.value(result); snapshot = H.snapshot(); H.check(snapshot, C.baseline.locale); }
            catch (_) {
                restoring = false; phase = 'recovery-error';
                if (attempt >= 3) { recoveryExhausted = true; setTimeout(function () { process.exit(2); }, 20000); }
                event('recovery-error', {code: 'RECOVERY_NOT_VERIFIED', attempt: attempt, snapshot: snapshot || null});
                if (!recoveryExhausted) setTimeout(function () { rollback(reason, rehearsal, attempt + 1); }, 1000);
                return;
            }
            restoring = false; dirty = false; tested = true; phase = rehearsal ? 'ready' : 'rolled-back';
            event(rehearsal ? 'probe-passed' : 'rolled-back', {snapshot: snapshot, reason: reason});
        }, 750);
    }
    function probe() {
        if (phase !== 'ready' || tested || used) throw new Error('PROBE_STATE_REJECTED'); phase = 'probe';
        child = cp.spawn('/usr/bin/node', ['-e', 'setInterval(function(){},1000);'], {stdio: 'ignore'}); var probeChild = child;
        event('probe-started', {watchdogPid: process.pid, watchdogParentPid: process.ppid, uid: process.getuid(), probePid: child.pid});
        probeChild.on('exit', function (_, signal) { if (phase === 'probe') { child = null; event('probe-exited', {signal: signal}); rollback('probe-timeout', true); } });
        probeChild.on('error', function () { event('error', {code: 'PROBE_SPAWN_FAILED'}); });
        setTimeout(function () { if (phase === 'probe') probeChild.kill('SIGKILL'); }, 1000);
    }
    function mutate() {
        if (phase !== 'ready' || !tested || used || process.ppid !== 1 || process.getuid() !== 0) throw new Error('WRITE_GATE_REJECTED');
        H.check(H.snapshot(), C.baseline.locale); used = true; dirty = true; phase = 'trial'; trialStart = Date.now();
        var code = 'var C=' + JSON.stringify(C) + ';var H=(' + helpers.toString() + ')(C);(' + worker.toString() + ')(C,H);';
        child = cp.spawn('/usr/bin/node', ['-e', code], {stdio: ['ignore', 'ignore', 'ignore', 'ipc']}); var workerChild = child;
        workerChild.on('message', function (m) {
            if (!m || ['write-request', 'write-response', 'immediate-read', 'delayed-read', 'decision', 'worker-error'].indexOf(m.name) < 0) { rollback('INVALID_WORKER_MESSAGE', false); return; }
            event(m.name, m.data, function () {
                if (m.name === 'worker-error') { rollback('WORKER_FAILED', false); return; }
                if (m.name === 'decision') {
                    if (!m.data.ok) { rollback('OBSERVATION_MISMATCH', false); return; }
                    var s;
                    try { s = H.snapshot(); if (!H.expected(s.locale)) throw new Error('SCOPE'); H.check(s, s.locale); }
                    catch (_) { event('invariant-failed', {snapshot: s || null}); rollback('PROTECTED_INVARIANT_FAILED', false); return; }
                    phase = 'visual'; visualStart = Date.now(); event('verified', {snapshot: s});
                }
                if (workerChild.connected) workerChild.send({ack: m.name});
            });
        });
        workerChild.on('exit', function () { if (child === workerChild) child = null; if (phase === 'trial') rollback('WORKER_EXITED', false); });
        workerChild.on('error', function () { rollback('WORKER_SPAWN_FAILED', false); });
    }
    function command(c) {
        if (!c || !Number.isInteger(c.id) || c.id <= lastId) return; lastId = c.id;
        try {
            if (c.action === 'probe') probe();
            else if (c.action === 'apply') mutate();
            else if (c.action === 'rollback') { if (dirty) rollback('CONTROLLER_REQUEST', false); }
            else if (c.action === 'accept') {
                if (phase !== 'visual') throw new Error('ACCEPT_STATE_REJECTED'); var s = H.snapshot(); if (!H.expected(s.locale)) throw new Error('SCOPE'); H.check(s, s.locale); dirty = false; phase = 'accepted'; event('accepted', {snapshot: s});
            } else if (c.action === 'finish') {
                if (dirty || restoring || phase === 'trial' || phase === 'probe') throw new Error('UNSAFE_FINISH');
                phase = 'finished'; event('finished', {used: used}, function () { stopped = true; process.exit(0); });
            } else throw new Error('UNKNOWN_ACTION');
        } catch (_) { event('error', {code: 'COMMAND_REJECTED'}); if (dirty) rollback('COMMAND_ERROR', false); }
    }
    function poll() { if (stopped) return; request('GET', '/command/' + C.token, null, function (error, c) { if (!error) command(c); if (!stopped) setTimeout(poll, 500); }); }
    process.on('uncaughtException', function () { event('error', {code: 'AGENT_EXCEPTION'}); if (dirty) rollback('AGENT_EXCEPTION', false); });
    try {
        var initial = H.audit(H.snapshot());
        if (C.operation === 'audit') { event('audit', {snapshot: initial}, function () { process.exit(0); }); setTimeout(function () { process.exit(1); }, 25000); return; }
        if (C.operation !== 'apply' && C.operation !== 'restore') throw new Error('INVALID_MODE');
        H.check(initial, C.baseline.locale); phase = 'ready'; event('ready', {snapshot: initial, watchdogPid: process.pid, watchdogParentPid: process.ppid, uid: process.getuid()}, poll);
    } catch (_) { event('error', {code: 'BASELINE_REJECTED'}, function () { process.exit(1); }); setTimeout(function () { process.exit(1); }, 20000); return; }
    setInterval(function () {
        if (stopped || restoring || recoveryExhausted || phase === 'recovery-error') return;
        if (dirty && (Date.now() - lastContact > 20000 || (phase === 'trial' && Date.now() - trialStart > 25000) || (phase === 'visual' && Date.now() - visualStart > C.visualSeconds * 1000))) { rollback('INDEPENDENT_TIMEOUT', false); return; }
        if (phase === 'visual') {
            try { var l = H.locale(); if (!H.expected(l.value) || !l.mirror || !H.same(l.value, l.mirror.localeInfo)) throw new Error('LOCALE_DRIFT'); if (Date.now() - lastCheck > 10000) { lastCheck = Date.now(); var s = H.snapshot(); H.check(s, s.locale); } }
            catch (_) { event('invariant-failed', {code: 'VISUAL_STAGE_DRIFT'}); rollback('VISUAL_STAGE_DRIFT', false); }
        }
        if (!dirty && Date.now() - lastContact > 30000 && Date.now() - start > 30000) process.exit(0);
    }, 1500);
})(__CONFIG__);
