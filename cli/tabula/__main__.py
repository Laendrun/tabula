"""`python -m tabula`, or `python cli/tabula` from a checkout without installing."""
import sys

if __package__ in (None, ""):          # run as `python cli/tabula`: make the package importable
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tabula.cli import main
else:
    from .cli import main

sys.exit(main())
