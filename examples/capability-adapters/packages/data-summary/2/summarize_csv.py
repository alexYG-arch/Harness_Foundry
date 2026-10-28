"""Explicit project CSV aggregation; standalone and independent of Foundry."""

import argparse
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re
import sys


DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
ROUNDINGS = {"HALF_UP", "HALF_EVEN", "DOWN"}


def number(value):
    # Decimal strings, not JSON floats or locale-dependent comma numbers.
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError("expected a finite decimal string: " + repr(value))
    return Fraction(value)


def exact(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def rounded(value, scale, mode):
    scaled = abs(value) * 10 ** scale
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = remainder * 2
    if mode == "HALF_UP" and twice >= scaled.denominator:
        whole += 1
    elif mode == "HALF_EVEN" and (twice > scaled.denominator or twice == scaled.denominator and whole % 2):
        whole += 1
    digits = str(whole).zfill(scale + 1)
    text = digits if scale == 0 else digits[:-scale] + "." + digits[-scale:]
    return ("-" if value < 0 and whole else "") + text


def fields(value, label):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value) or len(set(value)) != len(value):
        raise ValueError(label + " must be a list of distinct column names")
    return value


def validate(config):
    if not isinstance(config, dict) or set(config) != {"schema_version", "group_by", "filters", "rows", "metrics"}:
        raise ValueError("config requires schema_version, group_by, filters, rows, metrics only")
    if config["schema_version"] != "1.0":
        raise ValueError("unsupported project configuration version")
    required = set(fields(config["group_by"], "group_by"))
    policy = config["rows"]
    if not isinstance(policy, dict) or set(policy) != {"key", "duplicates", "missing"}:
        raise ValueError("rows requires key, duplicates, missing")
    required.update(fields(policy["key"], "rows.key"))
    if policy["duplicates"] not in {"error", "keep_first", "keep_last", "all"}:
        raise ValueError("unknown duplicate policy")
    if not policy["key"] and policy["duplicates"] != "all":
        raise ValueError("duplicate policy needs explicit key columns")
    if policy["missing"] not in {"error", "skip"}:
        raise ValueError("unknown missing policy")
    if not isinstance(config["filters"], list):
        raise ValueError("filters must be a list of equality comparisons")
    for rule in config["filters"]:
        if not isinstance(rule, dict) or set(rule) != {"column", "equals"} or not isinstance(rule["equals"], str):
            raise ValueError("filter requires column and string equals")
        required.update(fields([rule["column"]], "filter"))
    metrics = config["metrics"]
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("metrics must be a nonempty list")
    ids, base = set(), set()
    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("metric must be an object")
        common = {"id", "op", "scale", "rounding", "unit"}
        if not common.issubset(metric) or not isinstance(metric["id"], str) or not metric["id"] or metric["id"] in ids:
            raise ValueError("metric requires a distinct id and explicit display settings")
        ids.add(metric["id"])
        if type(metric["scale"]) is not int or metric["scale"] < 0 or metric["rounding"] not in ROUNDINGS or not isinstance(metric["unit"], str):
            raise ValueError("invalid metric scale, rounding or unit")
        op = metric["op"]
        if op == "sum":
            allowed = common | {"column", "unit_column", "unit_factors"}
            if "column" not in metric or not set(metric).issubset(allowed):
                raise ValueError("sum requires column; only explicit unit conversion is supported")
            required.update(fields([metric["column"]], "sum.column"))
            if ("unit_column" in metric) != ("unit_factors" in metric):
                raise ValueError("unit_column and unit_factors must be supplied together")
            if "unit_column" in metric:
                required.update(fields([metric["unit_column"]], "sum.unit_column"))
                factors = metric["unit_factors"]
                if not isinstance(factors, dict) or not factors or any(not isinstance(k, str) or not k for k in factors):
                    raise ValueError("unit_factors must name the allowed source units")
                if any(number(v) <= 0 for v in factors.values()):
                    raise ValueError("unit conversion factors must be positive")
            base.add(metric["id"])
        elif op == "count":
            if set(metric) != common:
                raise ValueError("count counts included rows and takes no column")
            base.add(metric["id"])
        elif op == "ratio":
            if set(metric) != common | {"numerator", "denominator", "zero_denominator"}:
                raise ValueError("ratio requires numerator, denominator and zero_denominator")
            if metric["zero_denominator"] not in {"error", "null"}:
                raise ValueError("unknown zero denominator policy")
        else:
            raise ValueError("supported metrics are sum, count, ratio")
    for metric in metrics:
        if metric["op"] == "ratio" and (metric["numerator"] not in base or metric["denominator"] not in base):
            raise ValueError("ratio references must name sum or count metrics")
    return required


def summarize(csv_bytes, config_bytes):
    config = json.loads(config_bytes)
    required = validate(config)
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""), strict=True)
    header = reader.fieldnames
    if not header or any(not h for h in header) or len(set(header)) != len(header):
        raise ValueError("CSV requires distinct nonempty column names")
    if not required.issubset(header):
        raise ValueError("CSV missing declared columns: " + ", ".join(sorted(required - set(header))))
    policy, metrics = config["rows"], config["metrics"]
    included, excluded, by_key = [], [], {}
    input_rows = 0
    for record, row in enumerate(reader, 1):
        input_rows += 1
        if None in row or None in row.values():
            raise ValueError("CSV record has a different width than its header: " + str(record))
        if any(row[rule["column"]] != rule["equals"] for rule in config["filters"]):
            excluded.append({"record": record, "reason": "filter"})
            continue
        missing = sorted(name for name in required if row[name] == "")
        if missing:
            if policy["missing"] == "error":
                raise ValueError("missing values at record " + str(record) + ": " + ", ".join(missing))
            excluded.append({"record": record, "reason": "missing", "columns": missing})
            continue
        contributions = {}
        for metric in metrics:
            if metric["op"] == "count":
                contributions[metric["id"]] = Fraction(1)
            elif metric["op"] == "sum":
                value = number(row[metric["column"]])
                if "unit_column" in metric:
                    unit = row[metric["unit_column"]]
                    if unit not in metric["unit_factors"]:
                        raise ValueError("undeclared source unit at record " + str(record) + ": " + unit)
                    value *= number(metric["unit_factors"][unit])
                contributions[metric["id"]] = value
        item = {"record": record, "group": {name: row[name] for name in config["group_by"]},
                "key": {name: row[name] for name in policy["key"]}, "contributions": contributions}
        key = tuple(row[name] for name in policy["key"])
        if policy["duplicates"] != "all" and key in by_key:
            if policy["duplicates"] == "error":
                raise ValueError("duplicate key at record " + str(record))
            if policy["duplicates"] == "keep_first":
                excluded.append({"record": record, "reason": "duplicate"})
                continue
            old = by_key[key]
            excluded.append({"record": old["record"], "reason": "duplicate"})
            included.remove(old)
        included.append(item)
        by_key[key] = item
    groups = {}
    for row in included:
        group = tuple(row["group"].values())
        totals = groups.setdefault(group, {m["id"]: Fraction(0) for m in metrics if m["op"] != "ratio"})
        for key, value in row["contributions"].items():
            totals[key] += value
    # An ungrouped empty dataset still has its explicit zero total/count.
    if not config["group_by"] and not groups:
        groups[()] = {m["id"]: Fraction(0) for m in metrics if m["op"] != "ratio"}
    results = []
    for group, totals in groups.items():
        values = {}
        for metric in metrics:
            if metric["op"] == "ratio":
                denominator = totals[metric["denominator"]]
                if denominator == 0 and metric["zero_denominator"] == "error":
                    raise ValueError("zero denominator for " + metric["id"])
                value = totals[metric["numerator"]] / denominator if denominator else None
            else:
                value = totals[metric["id"]]
            values[metric["id"]] = {"value": rounded(value, metric["scale"], metric["rounding"]) if value is not None else None,
                                    "exact": exact(value) if value is not None else None, "unit": metric["unit"]}
        results.append({"key": dict(zip(config["group_by"], group)), "metrics": values})
    return {"schema_version": "1.0", "input_sha256": hashlib.sha256(csv_bytes).hexdigest(),
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "summary": {"input_rows": input_rows, "included_rows": len(included), "excluded_rows": len(excluded)},
            "groups": results,
            "rows": [{**row, "contributions": {k: exact(v) for k, v in row["contributions"].items()}} for row in included],
            "excluded": sorted(excluded, key=lambda row: row["record"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ValueError("write the result to a project output location, not the capability package")
        result = summarize(args.input.read_bytes(), args.config.read_bytes())
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (ValueError, TypeError, KeyError, csv.Error, UnicodeError, OSError) as error:
        print("data-summary: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
