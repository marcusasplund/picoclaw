"""Task and failure based model selection; credentials stay in the runtime config."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re
import tempfile

from common import BASE

DEFAULT = {
    'source_alias': 'openai-fast',
    'plan': {'model': 'openai/gpt-5.6-luna', 'reasoning_effort': 'low',
             'input_per_million': 0.20, 'output_per_million': 1.20},
    'build': {'model': 'openai/gpt-5.6-luna', 'reasoning_effort': 'low',
              'input_per_million': 0.20, 'output_per_million': 1.20},
    'escalated': {'model': 'openai/gpt-5.6-terra', 'reasoning_effort': 'medium',
                  'input_per_million': 2.0, 'output_per_million': 12.0},
    'max_calls': 60, 'max_escalated_calls': 20, 'reserve_budget_usd': 10.0,
}

CONTINUE_CALLS = 20
CONTINUE_ESCALATED_CALLS = 10
CONTINUE_RESERVE_USD = 5.0


class PolicyError(RuntimeError):
    """A safe, user-facing routing/budget error (never contains credentials)."""


def policy():
    path = BASE / 'model-routing.json'
    value = json.loads(path.read_text()) if path.exists() else copy.deepcopy(DEFAULT)
    # Migrate only the model IDs introduced by the broken 5.4 default. Explicit
    # user choices and all job limits remain untouched.
    migrated = False
    for stage in ('plan', 'build'):
        if value[stage]['model'] == 'openai/gpt-5.4-mini':
            value[stage] = copy.deepcopy(DEFAULT[stage])
            migrated = True
    if value['escalated']['model'] == 'openai/gpt-5.4':
        value['escalated'] = copy.deepcopy(DEFAULT['escalated'])
        migrated = True
    if migrated:
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)
    for stage in ('plan', 'build', 'escalated'):
        target = value[stage]
        if not re.fullmatch(r'openai/gpt-5\.[a-zA-Z0-9.-]+', target['model']):
            raise PolicyError('Build routing requires an explicit OpenAI GPT-5 model ID.')
        if target['reasoning_effort'] not in ('none', 'low', 'medium', 'high'):
            raise PolicyError('Ogiltig reasoning_effort i model-routing.json.')
        for key in ('input_per_million', 'output_per_million'):
            if not 0 < target[key] < 1000:
                raise PolicyError('Ogiltigt prisunderlag i model-routing.json.')
    if not 1 <= value['max_calls'] <= 80 or not 1 <= value['max_escalated_calls'] <= value['max_calls']:
        raise PolicyError('Ogiltigt anropstak i model-routing.json.')
    if not 0 < value['reserve_budget_usd'] <= 100:
        raise PolicyError('Ogiltig budget i model-routing.json.')
    return value


class ModelPolicy:
    def __init__(self, cfg, plan, root, planning=False):
        self.cfg, self.root, self.plan = cfg, root, plan
        self.config = policy()
        self.path = root / 'model-usage.json'
        self.usage = json.loads(self.path.read_text()) if self.path.exists() else {
            'calls': 0, 'escalated_calls': 0, 'reserved_usd': 0.0,
            'estimated_cost_usd': 0.0, 'input_tokens': 0, 'output_tokens': 0, 'events': []}
        self.continuations = int(cfg.get('_continuations', 0))
        if not 0 <= self.continuations <= 3:
            raise PolicyError('Invalid manual continuation count.')
        # Auth/permissions merit the stronger model from the beginning. Also honor
        # escalation persisted by an earlier manually restarted build of this job.
        text = json.dumps(plan, ensure_ascii=False).lower()
        sensitive = re.search(r'\b(login|inloggning|autentisering|authentication|oauth|authorization|behörighet|multi.?tenant)\b', text)
        self.stage = 'plan' if planning else ('escalated' if sensitive or self.usage.get('escalated') else 'build')
        self.save()

    @property
    def label(self):
        return self.config[self.stage]['model'] + ' (' + self.config[self.stage]['reasoning_effort'] + ')'

    def save(self):
        self.usage['model'] = self.label
        self.usage['continuations'] = self.continuations
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.usage, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def escalate(self, reason):
        if self.stage == 'escalated':
            return False
        self.stage = 'escalated'
        self.usage['escalated'] = True
        self.usage['events'].append({'event': 'escalation', 'reason': reason, 'model': self.label})
        self.save()
        return True

    def record_usage(self, input_tokens, output_tokens):
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return
        target = self.config[self.stage]
        cost = (input_tokens * target['input_per_million'] +
                output_tokens * target['output_per_million']) / 1_000_000
        self.usage['input_tokens'] = self.usage.get('input_tokens', 0) + input_tokens
        self.usage['output_tokens'] = self.usage.get('output_tokens', 0) + output_tokens
        self.usage['estimated_cost_usd'] = self.usage.get('estimated_cost_usd', 0.0) + cost
        self.usage['events'].append({'event': 'usage', 'stage': self.stage,
                                     'input_tokens': input_tokens, 'output_tokens': output_tokens,
                                     'estimated_cost_usd': cost})
        self.save()

    @contextmanager
    def request_config(self, payload):
        source = json.loads(Path(self.cfg['runtime_config']).read_text())
        matches = [m for m in source.get('model_list', []) if m.get('model_name') == self.config['source_alias']]
        if not matches:
            raise PolicyError('The API connection model alias is missing: ' + self.config['source_alias'])
        entry = copy.deepcopy(matches[0])
        if not entry.get('model', '').startswith('openai/') or entry.get('provider', '') not in ('', 'openai'):
            raise PolicyError('Model routing requires the existing OpenAI API connection.')
        target = self.config[self.stage]
        entry.update(model_name='projectflow-selected', model=target['model'], provider='openai',
                     max_tokens_field='max_completion_tokens', request_timeout=180,
                     extra_body={'reasoning_effort': target['reasoning_effort']})
        for key in ('fallbacks', 'thinking_level', 'workspace', 'auth_method', 'connect_mode', 'streaming'):
            entry.pop(key, None)
        source['model_list'] = [entry]
        source['agents']['defaults']['model_name'] = entry['model_name']
        source['agents']['defaults'].pop('model', None)
        source['agents']['defaults'].pop('routing', None)
        # Reserve a deliberately conservative amount BEFORE every request,
        # including failed requests. This is not billed-token accounting.
        reservation = ((len(payload.encode()) + 4096) * target['input_per_million']
                       + 8192 * target['output_per_million']) / 1_000_000
        base_calls = min(self.config['max_calls'], 14) if self.plan.get('profile') == 'static' else self.config['max_calls']
        base_escalated = min(self.config['max_escalated_calls'], 4) if self.plan.get('profile') == 'static' else self.config['max_escalated_calls']
        max_calls = base_calls + self.continuations * CONTINUE_CALLS
        max_escalated = (base_escalated +
                         self.continuations * CONTINUE_ESCALATED_CALLS)
        reserve_budget = (self.config['reserve_budget_usd'] +
                          self.continuations * CONTINUE_RESERVE_USD)
        if (self.usage['calls'] >= max_calls
                or (self.stage == 'escalated' and self.usage['escalated_calls'] >= max_escalated)
                or self.usage['reserved_usd'] + reservation > reserve_budget):
            raise PolicyError('The model budget or call limit has been reached. See model-usage.json; it is not reset automatically.')
        self.usage['calls'] += 1
        self.usage['escalated_calls'] += int(self.stage == 'escalated')
        self.usage['reserved_usd'] += reservation
        self.usage['events'].append({'event': 'request', 'stage': self.stage, 'model': self.label,
                                     'reserved_usd': reservation})
        self.save()
        # Credentials exist only temporarily on host tmpfs, outside project paths.
        runtime = Path(self.cfg['runtime_config']).parent
        with tempfile.TemporaryDirectory(prefix='model-route-', dir=runtime) as directory:
            path = Path(directory) / 'config.json'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump(source, output)
            yield str(path)


if __name__ == '__main__':
    path = BASE / 'model-routing.json'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(DEFAULT, output, indent=2)
    value = policy()
    print('Planering:', value['plan']['model'])
    print('Kod:', value['build']['model'])
    print('Eskalering/login:', value['escalated']['model'])
    print('Anropstak:', value['max_calls'], '(varav', value['max_escalated_calls'], 'eskalerade)')
    print('Konservativ budgetreserv: USD', value['reserve_budget_usd'], 'per jobb, även över manuella återförsök')
