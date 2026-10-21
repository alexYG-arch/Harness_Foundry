"""Fixture checks only: these do not run a delivered Harness or accept its outputs."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'examples' / 'harness-composition-upgrade' / 'business'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def reference_orders():
    """Independently read the source rows; never use expected.json as input."""
    directory = ROOT / 'data-reasoning'
    definition = read_json(directory / 'inputs/metric-definition.json')
    with (directory / 'inputs/orders.csv').open(newline='', encoding='utf-8') as source:
        rows = list(csv.DictReader(source))
    latest = {}
    for row in rows:
        key = row['event_id']
        previous = latest.get(key)
        if previous is None or int(row['revision']) > int(previous['revision']):
            latest[key] = row
        elif int(row['revision']) == int(previous['revision']) and row != previous:
            raise AssertionError(f'Conflicting source revision: {key}')
    zone = timezone(timedelta(hours=definition['timezone_offset_hours']))
    result = {}
    for key, row in latest.items():
        local_time = datetime.fromisoformat(row['occurred_at']).astimezone(zone)
        if local_time.date().isoformat() != definition['target_date'] or row['status'] != definition['status']:
            continue
        amount = None if not row['amount'] else Decimal(row['amount']) * Decimal(definition['units_to_yuan'][row['unit']])
        result[key] = {'amount': amount, 'channel': row['channel'], 'local_time': local_time.isoformat()}
    return rows, latest, result


class HarnessBusinessFixtureTests(unittest.TestCase):
    def test_three_groups_have_resolvable_independent_inputs_and_planned_outputs(self):
        manifest = read_json(ROOT / 'manifest.json')
        self.assertEqual({g['id'] for g in manifest['groups']}, {'prd_design', 'data_reasoning', 'market_research'})
        self.assertEqual(manifest['protocol_version'], '2.9')
        for group in manifest['groups']:
            manifest_path = ROOT / group['manifest']
            self.assertTrue(manifest_path.is_file())
            directory = manifest_path.parent
            spec = read_json(manifest_path)
            self.assertEqual(spec['status'], 'EXECUTION_NOT_RUN')
            refs = spec['inputs'] + [spec['task'], spec['expected'], spec['counterexamples'], spec['upgrade'], spec['tool_preparation']] + list(spec['workflows'].values())
            if 'live_task' in spec:
                refs.append(spec['live_task'])
            for ref in refs:
                path = (directory / ref).resolve()
                self.assertTrue(path.is_relative_to(ROOT.resolve()), ref)
                self.assertTrue(path.is_file(), ref)
            expected = read_json(directory / spec['expected'])
            for ref in expected['basis']:
                self.assertIn(ref, spec['inputs'])
                self.assertTrue((directory / ref).is_file())
            for output in spec['outputs'] + spec['v2_additional_outputs'] + spec.get('live_outputs', []):
                self.assertFalse((directory / output).exists(), 'Fixture preparation must not pre-fill business outputs')
                self.assertFalse(Path(output).is_absolute())
                self.assertNotIn('..', Path(output).parts)
            self.assertNotEqual((directory / spec['workflows']['v1']).read_bytes(), (directory / spec['workflows']['v2']).read_bytes())

    def test_prd_expectations_trace_original_requirements_not_generated_prd(self):
        directory = ROOT / 'prd-design'
        original = (directory / 'inputs/brief.md').read_text(encoding='utf-8')
        expected = read_json(directory / 'expected.json')
        source_ids = set(re.findall(r'^- (R\d+)[：:]', original, re.M))
        self.assertEqual(source_ids, {item['id'] for item in expected['requirements']})
        self.assertEqual(len(source_ids), 8)
        self.assertTrue({'empty', 'offline_draft', 'network_error', 'capacity_conflict', 'confirmed'} <= set(expected['required_states']))
        self.assertEqual({view['width_px'] for view in expected['required_views']}, {375, 1280})
        negative = read_json(directory / 'counterexamples.json')
        for case in negative:
            self.assertTrue(set(case['violates']) <= source_ids)
        self.assertIn('R03', negative[0]['omitted_requirements'])
        self.assertEqual(negative[1]['network_state'], 'offline')
        self.assertEqual(negative[1]['display_state'], 'confirmed')
        self.assertFalse(negative[2]['mobile_button_visible'])
        self.assertFalse(negative[2]['keyboard_reachable'])

    def test_prd_upgrade_preserves_decisions_and_adds_behavior_not_new_input(self):
        directory = ROOT / 'prd-design'
        custom = read_json(directory / 'inputs/user-customization.json')
        expected = read_json(directory / 'expected.json')
        self.assertEqual(custom['reservation_authority'], 'server_confirmation')
        self.assertTrue(custom['preserve_contact_draft_on_retry'])
        self.assertEqual(expected['v2_addition']['artifact'], 'state-transitions.json')
        self.assertIn('offline_draft -> pending_user_retry -> submitting -> confirmed', expected['v2_addition']['must_trace'])
        negative = read_json(directory / 'counterexamples.json')[-1]
        self.assertTrue(set(negative['changed_customizations']) <= custom.keys())

    def test_data_source_has_actual_duplicates_revisions_and_local_date_boundaries(self):
        rows, latest, scoped = reference_orders()
        expected = read_json(ROOT / 'data-reasoning/expected.json')['hand_calculation']
        self.assertEqual(len(rows), 11)
        self.assertEqual(len(latest), 9)
        self.assertEqual(latest['b002']['revision'], '2')
        self.assertEqual(set(scoped), set(expected['scoped_paid_ids']))
        for key, time in expected['local_time_checks'].items():
            calculated = datetime.fromisoformat(latest[key]['occurred_at']).astimezone(timezone(timedelta(hours=8))).isoformat()
            self.assertEqual(calculated, time)
        self.assertEqual(scoped['b001']['amount'], Decimal('12'))
        self.assertNotIn('b009', scoped)
        self.assertEqual({key for key, row in scoped.items() if row['amount'] is None}, set(expected['unknown_amount_ids']))
        self.assertTrue(set(expected['excluded']['cancelled']).isdisjoint(scoped))
        self.assertTrue(set(expected['excluded']['outside_local_date']).isdisjoint(scoped))

    def test_independent_decimal_computation_matches_hand_calculation(self):
        _, _, scoped = reference_orders()
        expected = read_json(ROOT / 'data-reasoning/expected.json')
        metrics = expected['metrics']
        known = {key: row['amount'] for key, row in scoped.items() if row['amount'] is not None}
        subtotal = sum(known.values(), Decimal(0))
        mean = subtotal / len(known)
        self.assertEqual(known, {k: Decimal(v) for k, v in expected['hand_calculation']['known_amounts_yuan'].items()})
        self.assertEqual(len(scoped), metrics['eligible_paid_count'])
        self.assertEqual(len(known), metrics['known_amount_count'])
        self.assertEqual(len(scoped) - len(known), metrics['unknown_amount_count'])
        self.assertEqual(subtotal, Decimal(metrics['known_revenue_yuan']))
        self.assertEqual(Decimal(len(known)) / len(scoped), Decimal(metrics['amount_coverage']))
        self.assertEqual(mean, Decimal(metrics['known_amount_mean_exact_yuan']))
        self.assertEqual(mean.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), Decimal(metrics['known_amount_mean_display_yuan']))
        self.assertIsNone(metrics['complete_revenue_yuan'])
        self.assertIsNone(metrics['complete_mean_yuan'])
        self.assertIsNone(metrics['growth_rate'])

    def test_v2_group_reconciliation_and_conditional_bounds(self):
        _, _, scoped = reference_orders()
        directory = ROOT / 'data-reasoning'
        expected = read_json(directory / 'expected.json')['v2']
        config = read_json(directory / 'inputs/user-customization.json')
        for channel, group in expected['groups'].items():
            members = [row for row in scoped.values() if row['channel'] == channel]
            known = [row['amount'] for row in members if row['amount'] is not None]
            self.assertEqual(len(members), group['eligible_paid_count'])
            self.assertEqual(len(known), group['known_amount_count'])
            self.assertEqual(sum(known, Decimal(0)), Decimal(group['known_revenue_yuan']))
        lower = sum((row['amount'] for row in scoped.values() if row['amount'] is not None), Decimal(0))
        unknown = sum(row['amount'] is None for row in scoped.values())
        upper = lower + unknown * Decimal(config['sensitivity_missing_amount_cap_yuan'])
        bounds = expected['conditional_sensitivity']
        self.assertEqual(lower, Decimal(bounds['revenue_min_yuan']))
        self.assertEqual(upper, Decimal(bounds['revenue_max_yuan']))
        self.assertEqual(lower / len(scoped), Decimal(bounds['all_paid_mean_min_yuan']))
        self.assertEqual(upper / len(scoped), Decimal(bounds['all_paid_mean_max_yuan']))
        self.assertFalse(bounds['is_actual_complete_revenue'])

    def test_data_negative_samples_represent_numerical_and_reasoning_errors(self):
        directory = ROOT / 'data-reasoning'
        expected = read_json(directory / 'expected.json')['metrics']
        cases = {case['id']: case for case in read_json(directory / 'counterexamples.json')}
        self.assertNotEqual(cases['DATA-C1']['wrong_claim']['known_revenue_yuan'], expected['known_revenue_yuan'])
        self.assertIsNone(expected['complete_revenue_yuan'])
        self.assertIsNotNone(cases['DATA-C2']['wrong_claim']['complete_revenue_yuan'])
        self.assertNotEqual(cases['DATA-C3']['wrong_claim']['known_amount_mean_display_yuan'], expected['known_amount_mean_display_yuan'])
        _, _, scoped = reference_orders()
        self.assertNotEqual(set(cases['DATA-C4']['wrong_claim']['scoped_paid_ids']), set(scoped))
        self.assertEqual(cases['DATA-C5']['wrong_claim']['known_revenue_yuan'], expected['known_revenue_yuan'])
        self.assertIsNone(expected['growth_rate'])
        self.assertIsNotNone(cases['DATA-C5']['wrong_claim']['growth_rate'])
        self.assertTrue(cases['DATA-C6']['wrong_claim']['is_actual_complete_revenue'])

    def test_market_citations_point_to_actual_synthetic_source_paragraphs(self):
        directory = ROOT / 'market-research'
        source_index = read_json(directory / 'inputs/sources.json')
        self.assertTrue(source_index['all_sources_synthetic'])
        citation_keys = set()
        for source in source_index['sources']:
            path = directory / 'inputs' / source['filename']
            text = path.read_text(encoding='utf-8')
            self.assertIn('合成来源', text)
            self.assertIn(source['published'], text)
            actual = set(re.findall(r'^## (P\d+)$', text, re.M))
            self.assertEqual(actual, set(source['paragraph_ids']))
            citation_keys.update(source['source_id'] + ':' + p for p in actual)
        expected = read_json(directory / 'expected.json')
        for item in expected['supported_observations'] + expected['conflicts'] + expected['unsupported_claims']:
            self.assertTrue(set(item['citations']) <= citation_keys)
        for case in read_json(directory / 'counterexamples.json'):
            self.assertTrue(set(case.get('citations', []) + case.get('omitted_citations', [])) <= citation_keys)
        self.assertEqual(expected['live_branch_status'], 'NOT_RUN')

    def test_market_proportions_and_conflicting_prices_are_grounded(self):
        directory = ROOT / 'market-research'
        expected = read_json(directory / 'expected.json')
        counts = re.findall(r'(\d+) 位', (directory / 'inputs/sources/S01-interest-2024.md').read_text(encoding='utf-8'))
        self.assertEqual(len(counts), 2)
        denominator, numerator = map(int, counts)
        counts2 = re.findall(r'(\d+) 名', (directory / 'inputs/sources/S02-pilot-2026.md').read_text(encoding='utf-8'))
        self.assertEqual(len(counts2), 2)
        denominator2, numerator2 = map(int, counts2)
        for n, d, observed in [(numerator, denominator, expected['supported_observations'][0]), (numerator2, denominator2, expected['supported_observations'][1])]:
            self.assertEqual((n, d), (observed['numerator'], observed['denominator']))
            self.assertEqual(Decimal(n) / d, Decimal(observed['ratio']))
        prices = []
        for filename in ['S03-vendor-price.md', 'S04-community-price.md']:
            text = (directory / 'inputs/sources' / filename).read_text(encoding='utf-8')
            prices.append(re.search(r'每月 (\d+) 元', text).group(1))
        self.assertEqual(prices, expected['conflicts'][0]['values_yuan'])
        self.assertNotEqual(*prices)

    def test_market_negative_samples_do_not_convert_fixed_sources_into_live_proof(self):
        directory = ROOT / 'market-research'
        cases = {case['id']: case for case in read_json(directory / 'counterexamples.json')}
        self.assertIn('S01:P1', cases['MARKET-C1']['citations'])
        self.assertIn('S03:P2', cases['MARKET-C2']['citations'])
        self.assertIn('S04:P1', cases['MARKET-C3']['omitted_citations'])
        self.assertEqual(set(cases['MARKET-C4']['citations']), {'S01:P1', 'S02:P1'})
        self.assertFalse(cases['MARKET-C5']['live_search_performed'])
        self.assertTrue(cases['MARKET-C5']['claims_live_acceptance'])


if __name__ == '__main__':
    unittest.main()
