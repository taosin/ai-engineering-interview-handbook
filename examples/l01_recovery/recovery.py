"""L01: two independent durable stores and a deliberately small recovery protocol.

Only synthetic inventory is changed. No network, credentials or model is used.
The tool's idempotency ledger is authoritative; an Agent checkpoint is not a
transaction spanning the tool. See README.md for the contract and limitations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


class ParameterConflict(ValueError):
    """An existing logical operation/key cannot acquire different parameters."""


class ContractConflict(ValueError):
    """Recovery cannot reinterpret an already bound downstream contract."""


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def payload(params):
    if not isinstance(params, dict) or set(params) != {'order_id', 'sku', 'qty'}:
        raise ValueError('params must contain exactly order_id, sku and qty')
    if any(not isinstance(params[k], str) or not params[k].strip() for k in ('order_id', 'sku')):
        raise ValueError('order_id and sku must be nonempty strings')
    if type(params['qty']) is not int or params['qty'] <= 0:
        raise ValueError('qty must be a positive integer')
    return encode(params)


@contextmanager
def connection(path, *, write=False):
    # Explicit transaction control works on Python 3.10+; no cross-store ATTACH.
    con = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        if write:
            con.execute('BEGIN IMMEDIATE')
        yield con
        if write:
            con.commit()
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def event(con, kind, key, detail):
    con.execute('INSERT INTO events(time_ns,kind,operation_key,detail) VALUES(?,?,?,?)',
                (time.time_ns(), kind, key, encode(detail)))


def rows(con, table):
    # table is always an internal constant, never supplied by a caller.
    return [dict(row) for row in con.execute(f'SELECT * FROM {table} ORDER BY rowid')]


def initialize(root):
    """Initialize an empty lab or reopen it, without resetting existing data."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    events = '''CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, time_ns INTEGER NOT NULL, kind TEXT NOT NULL,
        operation_key TEXT NOT NULL, detail TEXT NOT NULL);'''
    with connection(root / 'tool.sqlite3') as con:
        con.executescript(events + '''
            CREATE TABLE IF NOT EXISTS inventory(sku TEXT PRIMARY KEY, available INTEGER NOT NULL CHECK(available>=0));
            CREATE TABLE IF NOT EXISTS requests(operation_key TEXT PRIMARY KEY, params TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(operation_key TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                sku TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0));
            INSERT OR IGNORE INTO inventory VALUES('SKU-A',10);
        ''')
    with connection(root / 'agent.sqlite3') as con:
        con.executescript(events + '''
            CREATE TABLE IF NOT EXISTS operations(
                operation_id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE, params TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('prepared','unknown','succeeded','failed')),
                calls INTEGER NOT NULL DEFAULT 0, max_calls INTEGER NOT NULL CHECK(max_calls>0),
                result TEXT, halt_reason TEXT, retry_contract TEXT
                    CHECK(retry_contract IN ('durable_idempotency','no_safe_retry')));
            CREATE TABLE IF NOT EXISTS attempts(
                attempt_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL,
                kind TEXT NOT NULL, automatic INTEGER NOT NULL, time_ns INTEGER NOT NULL);
        ''')


class ToolStore:
    """Mock service: immutable same-key results, parameter checks, atomic effects."""

    def __init__(self, path):
        self.path = Path(path)

    def reserve(self, key, params, fail_mid_transaction=False):
        if not isinstance(key, str) or not key.strip():
            raise ValueError('idempotency key is required')
        body = payload(params)
        with connection(self.path, write=True) as con:
            previous = con.execute('SELECT * FROM requests WHERE operation_key=?', (key,)).fetchone()
            if previous:
                if previous['params'] != body:
                    raise ParameterConflict('same key, different params')
                event(con, 'deduplicated', key, params)
                return json.loads(previous['result'])
            inventory = con.execute('SELECT available FROM inventory WHERE sku=?', (params['sku'],)).fetchone()
            if inventory is None or inventory['available'] < params['qty']:
                result = {'status': 'failed', 'reason': 'unknown_sku' if inventory is None else 'insufficient_stock'}
            else:
                available = inventory['available'] - params['qty']
                con.execute('UPDATE inventory SET available=? WHERE sku=?', (available, params['sku']))
                if fail_mid_transaction:
                    raise RuntimeError('injected failure before reservation and result persistence')
                con.execute('INSERT INTO reservations VALUES(?,?,?,?)',
                            (key, params['order_id'], params['sku'], params['qty']))
                result = {'status': 'succeeded', 'reservation_key': key, 'available': available}
            con.execute('INSERT INTO requests VALUES(?,?,?)', (key, body, encode(result)))
            event(con, 'reserve_applied' if result['status'] == 'succeeded' else 'reserve_rejected', key, result)
            return result  # connection context commits before the caller receives this value

    def lookup(self, key, params):
        if not isinstance(key, str) or not key.strip():
            raise ValueError('idempotency key is required')
        body = payload(params)
        with connection(self.path) as con:
            record = con.execute('SELECT * FROM requests WHERE operation_key=?', (key,)).fetchone()
            if record is None:
                return None
            if record['params'] != body:
                raise ParameterConflict('query params differ from original request')
            return json.loads(record['result'])

    def snapshot(self):
        with connection(self.path) as con:
            con.execute('BEGIN')  # one store's consistent read snapshot
            return {'stock': dict(con.execute('SELECT sku,available FROM inventory')),
                    'reservations': rows(con, 'reservations'), 'requests': rows(con, 'requests'),
                    'events': rows(con, 'events')}


class AgentStore:
    """Intent and remote-call budget survive restart; terminal results are monotone."""

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError('unknown operation')
        result = dict(row)
        result['key'] = result.pop('operation_key')
        result['params'] = json.loads(result['params'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def prepare(self, operation_id, params, max_calls=4):
        body = payload(params)
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError('operation_id is required')
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError('max_calls must be a positive integer')
        with connection(self.path, write=True) as con:
            inserted = con.execute('''INSERT OR IGNORE INTO operations
                (operation_id,operation_key,params,state,max_calls) VALUES(?,?,?,'prepared',?)''',
                (operation_id, str(uuid.uuid4()), body, max_calls)).rowcount
            row = con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if row['params'] != body or row['max_calls'] != max_calls:
                raise ParameterConflict('persisted intent or budget differs')
            if inserted:
                event(con, 'intent_saved', row['operation_key'], {'operation_id': operation_id, 'params': params})
            # A racing caller always adopts the stored key, not its discarded UUID.
            return self.decode(row)

    def read(self, operation_id):
        with connection(self.path) as con:
            return self.decode(con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())

    def bind_contract(self, operation_id, idempotent):
        if type(idempotent) is not bool:
            raise ValueError('idempotent must be a boolean')
        contract = 'durable_idempotency' if idempotent else 'no_safe_retry'
        with connection(self.path, write=True) as con:
            row = self.decode(con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
            if row['retry_contract'] is None:
                if row['calls']:
                    raise ContractConflict('cannot bind a new contract after an unbound call')
                con.execute('UPDATE operations SET retry_contract=? WHERE operation_id=?', (contract, operation_id))
                event(con, 'contract_bound', row['key'], {'retry_contract': contract})
            elif row['retry_contract'] != contract:
                raise ContractConflict('persisted downstream contract differs; no call issued')

    def claim_call(self, operation_id, kind, automatic=True, *, require_prepared=False):
        if kind not in {'write', 'query', 'manual_query'}:
            raise ValueError('unsupported call kind')
        if (kind == 'manual_query') != (not automatic):
            raise ValueError('only explicit manual queries may bypass the automatic budget')
        with connection(self.path, write=True) as con:
            row = self.decode(con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
            if row['state'] in {'succeeded', 'failed'}:
                return None
            if require_prepared and row['state'] != 'prepared':
                return None
            if automatic and row['calls'] >= row['max_calls']:
                con.execute("UPDATE operations SET halt_reason='budget_exhausted; reconcile_required' WHERE operation_id=?", (operation_id,))
                event(con, 'budget_exhausted', row['key'], {'calls': row['calls']})
                return None
            attempt_id = str(uuid.uuid4())
            con.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',
                        (attempt_id, operation_id, kind, int(automatic), time.time_ns()))
            # Mark uncertainty before crossing the independent service boundary.
            con.execute("UPDATE operations SET state='unknown', calls=calls+?, halt_reason=NULL WHERE operation_id=?",
                        (int(automatic), operation_id))
            event(con, 'call_reserved', row['key'], {'attempt_id': attempt_id, 'kind': kind, 'automatic': automatic})
            return attempt_id

    def finish(self, operation_id, result):
        if not isinstance(result, dict) or result.get('status') not in {'succeeded', 'failed'}:
            raise ValueError('a confirmed tool result is required')
        with connection(self.path, write=True) as con:
            row = self.decode(con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
            if row['state'] in {'succeeded', 'failed'}:
                if row['result'] != result:
                    raise ValueError('contradictory terminal result requires investigation')
                return
            con.execute('UPDATE operations SET state=?, result=?, halt_reason=? WHERE operation_id=?',
                        (result['status'], encode(result), result.get('reason'), operation_id))
            event(con, 'checkpoint_saved', row['key'], result)

    def note_unknown(self, operation_id, reason):
        with connection(self.path, write=True) as con:
            row = self.decode(con.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
            if row['state'] in {'succeeded', 'failed'}:
                event(con, 'late_unknown_ignored', row['key'], {'reason': reason})
                return
            con.execute("UPDATE operations SET state='unknown', halt_reason=? WHERE operation_id=?", (reason, operation_id))
            event(con, 'unknown', row['key'], {'reason': reason})

    def snapshot(self):
        with connection(self.path) as con:
            con.execute('BEGIN')
            return {'operations': [self.decode(row) for row in con.execute('SELECT * FROM operations ORDER BY rowid')],
                    'attempts': rows(con, 'attempts'), 'events': rows(con, 'events')}


class ToolClient:
    """In-process transport faults; faults occur after the service transaction ends."""

    def __init__(self, tool, *, drop_response=False, offline=False, query_offline=False,
                 idempotent=True, fault=None, before_reserve=None):
        self.tool = tool
        self.drop_response = drop_response
        self.offline = offline
        self.query_offline = query_offline
        self.idempotent = idempotent
        self.fault = fault
        self.before_reserve = before_reserve

    def reserve(self, key, params):
        if self.before_reserve:
            self.before_reserve()  # outside both stores' write transactions
        if self.offline:
            raise TimeoutError('request outcome unavailable')
        # Non-idempotent mode models a service that does not honor the supplied key.
        result = self.tool.reserve(key if self.idempotent else str(uuid.uuid4()), params)
        if self.fault == 'after-tool-commit':
            os._exit(71)
        if self.drop_response:
            raise TimeoutError('response lost after tool commit')
        return result

    def lookup(self, key, params):
        if not self.idempotent or self.query_offline:
            raise TimeoutError('query unavailable; this is not NOT_FOUND')
        return self.tool.lookup(key, params)


class Agent:
    def __init__(self, store, client, *, fault=None):
        self.store = store
        self.client = client
        self.fault = fault

    def _confirm(self, operation_id, result):
        if self.fault == 'before-checkpoint':
            os._exit(72)
        self.store.finish(operation_id, result)
        return self.store.read(operation_id)

    def _record_storage_error(self, operation_id, error):
        # Report lock contention without converting unknown into business failure.
        code = getattr(error, 'sqlite_errorcode', 0) & 0xff
        if code in (5, 6) or str(error) in ('database is locked', 'database table is locked'):
            self.store.note_unknown(operation_id, 'storage_locked; reconcile_required')

    def recover(self, operation_id):
        self.store.bind_contract(operation_id, self.client.idempotent)
        while True:
            op = self.store.read(operation_id)
            if op['state'] in {'succeeded', 'failed'}:
                return op
            if op['state'] == 'unknown':
                if not self.client.idempotent:
                    self.store.note_unknown(operation_id, 'no_safe_retry_contract; reconcile_required')
                    return self.store.read(operation_id)
                if self.store.claim_call(operation_id, 'query') is None:
                    return self.store.read(operation_id)
                try:
                    result = self.client.lookup(op['key'], op['params'])
                    if result is not None:
                        return self._confirm(operation_id, result)
                except TimeoutError:
                    self.store.note_unknown(operation_id, 'query_unavailable')
                except sqlite3.OperationalError as error:
                    self._record_storage_error(operation_id, error)
                    raise
                # NOT_FOUND or query unavailable permits a same-key retry ONLY
                # under this mock service's strong durable idempotency contract.
            if self.store.claim_call(operation_id, 'write', require_prepared=not self.client.idempotent) is None:
                return self.store.read(operation_id)
            try:
                result = self.client.reserve(op['key'], op['params'])
                return self._confirm(operation_id, result)
            except TimeoutError:
                self.store.note_unknown(operation_id, 'write_outcome_unknown')
            except sqlite3.OperationalError as error:
                self._record_storage_error(operation_id, error)
                raise

    def reconcile(self, operation_id):
        """Explicit, audited read-only reconciliation after stopping automation."""
        self.store.bind_contract(operation_id, self.client.idempotent)
        op = self.store.read(operation_id)
        if op['state'] in {'succeeded', 'failed'}:
            return op
        if not self.client.idempotent:
            self.store.note_unknown(operation_id, 'external_manual_reconciliation_required')
            return self.store.read(operation_id)
        if self.store.claim_call(operation_id, 'manual_query', automatic=False) is None:
            return self.store.read(operation_id)
        try:
            result = self.client.lookup(op['key'], op['params'])
        except TimeoutError:
            result = None
        except sqlite3.OperationalError as error:
            self._record_storage_error(operation_id, error)
            raise
        if result is not None:
            return self._confirm(operation_id, result)
        self.store.note_unknown(operation_id, 'unresolved; no_new_write_issued')
        return self.store.read(operation_id)


def main():
    parser = argparse.ArgumentParser(description='Resume one prepared synthetic L01 operation')
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--operation', required=True)
    parser.add_argument('--fault', choices=['after-tool-commit', 'before-checkpoint'])
    args = parser.parse_args()
    initialize(args.directory)
    store = AgentStore(args.directory / 'agent.sqlite3')
    client = ToolClient(ToolStore(args.directory / 'tool.sqlite3'), fault=args.fault)
    result = Agent(store, client, fault=args.fault).recover(args.operation)
    print(encode(result))


if __name__ == '__main__':
    main()
