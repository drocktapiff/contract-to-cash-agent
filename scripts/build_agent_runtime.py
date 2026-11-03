"""Build an explicit runtime allowlist, excluding generators, tests, and answer keys."""
import argparse
from pathlib import Path
import shutil


def build(destination: Path):
    source = Path(__file__).resolve().parents[1] / 'contract_to_cash'
    destination = destination.resolve()
    # Never overwrite or merge an unknown directory, or nest under the source.
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Choose a new destination outside the source package')
    target = destination / 'contract_to_cash'
    paths = ['__init__.py', 'billing_engine.py',
             'agent/__init__.py', 'agent/__main__.py', 'agent/runtime.py', 'agent/tools.py',
             'agent/events.py', 'agent/review.py', 'agent/INSTRUCTIONS.md',
             'data/contracts.json', 'data/amendments.json', 'data/invoices.json',
             'data/document_hashes.json']
    # Document IDs come exclusively from the manifest, validated below by PublicData.
    from contract_to_cash.agent.tools import PublicData
    data = PublicData(source / 'data', '2026-04')
    paths += ['data/documents/' + did + '.txt' for did in data.documents]
    for relative in paths:
        file = source / relative
        if file.is_symlink():
            raise ValueError('Symlinked runtime files are unsupported')
    for relative in paths:
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, output)
    shutil.copyfile(source.parent / 'requirements-agent.txt', destination / 'requirements-agent.txt')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(build(parser.parse_args().destination))
