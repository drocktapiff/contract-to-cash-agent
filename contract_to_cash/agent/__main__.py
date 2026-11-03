"""CLI for real OpenAI investigations and separate local operator review."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from .events import Journal
from .runtime import Investigator, Limits
from .tools import PublicData, Tools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Launch actual OpenAI Responses API requests')
    run.add_argument('--model', required=True)
    run.add_argument('--objective', default='Audit all customers for contractual billing discrepancies. Challenge findings and investigate shared patterns. Request human review; do not change billing.')
    run.add_argument('--period', default='2026-04')
    run.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    run.add_argument('--output', type=Path, default=Path('runs') / uuid4().hex)
    run.add_argument('--max-tool-calls', type=int, default=500)
    run.add_argument('--max-seconds', type=float, default=900)
    run.add_argument('--max-cost-usd', type=Decimal, default=Decimal('5'))
    run.add_argument('--input-price-per-million', type=Decimal, required=True)
    run.add_argument('--output-price-per-million', type=Decimal, required=True)
    run.add_argument('--max-output-tokens', type=int, default=4096)
    run.add_argument('--max-responses', type=int, default=600)
    run.add_argument('--watch-data', action='store_true', help='Accept real operator public-data updates at response boundaries')
    review = commands.add_parser('review', help='Human review/export only; never called by the model')
    review.add_argument('--run', type=Path, required=True)
    review.add_argument('--finding-id', required=True)
    review.add_argument('--decision', choices=['approved', 'rejected', 'needs_information'], required=True)
    review.add_argument('--reviewer', required=True)
    args = parser.parse_args(argv)
    if args.command == 'review':
        from .review import decide
        try:
            print(json.dumps(decide(args.run, args.finding_id, args.decision, args.reviewer), indent=2))
        except Exception as exc:
            print('Review failed: ' + type(exc).__name__, file=sys.stderr)
            return 2
        return 0
    if (args.data / 'sealed_answer_key.json').exists():
        parser.error('Agent data must exclude the sealed answer key; build and run the isolated runtime bundle')
    key = os.environ.get('OPENAI_API_KEY') or os.environ.get('CONTRACT_AGENT_API_KEY')
    if not key:
        parser.error('Set OPENAI_API_KEY (or proxy-backed CONTRACT_AGENT_API_KEY); never commit credentials')
    try:
        limits = Limits(args.max_tool_calls, args.max_seconds, args.max_cost_usd,
                        args.input_price_per_million, args.output_price_per_million,
                        args.max_output_tokens, args.max_responses)
        data = PublicData(args.data, args.period)
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url='https://api.openai.com/v1', max_retries=0)
        journal = Journal(args.output, sink=lambda line: print(line, flush=True))
    except Exception as exc:
        print('Setup failed: ' + type(exc).__name__ + '; check data integrity, limits, SDK installation, and output directory.', file=sys.stderr)
        return 2
    try:
        report = Investigator(client, args.model, Tools(data, journal), journal, limits, args.watch_data).run(args.objective)
        print('Report: ' + str(args.output / 'report.json'), file=sys.stderr)
        return 0 if report['status'] == 'completed' else 1
    finally:
        journal.close()
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
