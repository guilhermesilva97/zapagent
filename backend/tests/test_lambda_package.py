import io
import zipfile

from zapagent.entrypoints.bootstrap import build_lambda_zip


def test_lambda_zip_contains_only_the_webhook_package() -> None:
    with zipfile.ZipFile(io.BytesIO(build_lambda_zip())) as archive:
        names = sorted(archive.namelist())

    assert names == [
        "zapagent/__init__.py",
        "zapagent/webhook/__init__.py",
        "zapagent/webhook/handler.py",
        "zapagent/webhook/payload.py",
        "zapagent/webhook/signature.py",
    ]


def test_lambda_zip_is_deterministic_and_readable() -> None:
    first, second = build_lambda_zip(), build_lambda_zip()
    assert first == second

    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        for entry in archive.infolist():
            mode = entry.external_attr >> 16
            assert mode & 0o444 == 0o444, f"{entry.filename} sem permissão de leitura"
