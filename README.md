# cfn-drift-report

Turn AWS CloudFormation drift results into a readable report: which resources drifted, which properties changed, and by how much.

**Status:** v0.1. Offline reports from `describe-stack-resource-drifts` JSON (one file, a directory of stacks, or stdin) work today, with ignore rules, text/Markdown/JSON output and a drift exit code. A live `--detect` mode runs drift detection through boto3; it is tested with botocore's Stubber only and has not been run against a real account yet.

## Install

```bash
pip install git+https://github.com/narayana006/cfn-drift-report
# live --detect mode also needs boto3:
pip install "cfn-drift-report[aws] @ git+https://github.com/narayana006/cfn-drift-report"
```

Python 3.10 or newer. The offline mode has no dependencies.

## Quick start

The `examples/` directory holds illustrative, hand-written drift results for two fictional stacks in account 123456789012 (shaped exactly like `aws cloudformation describe-stack-resource-drifts` output), plus an ignore file.

```bash
cfn-drift-report examples/drifts --ignore-file examples/ignore.txt
```

Real output:

```text
data-prod: IN_SYNC (2 in sync)

web-prod: DRIFTED (3 modified, 1 deleted, 1 ignored, 2 in sync)
  ~ AssetsBucket  AWS::S3::Bucket  acme-web-prod-assets  MODIFIED
      ~ /VersioningConfiguration/Status  "Enabled" -> "Suspended"
      + /Tags/1  added {"Key":"cost-center","Value":"cc-1042"}
  ~ JobsQueue  AWS::SQS::Queue  https://sqs.us-east-1.amazonaws.com/123456789012/web-prod-jobs  MODIFIED
      ~ /DelaySeconds  20 -> 120  (+100, +500%)
      ~ /MessageRetentionPeriod  345600 -> 1209600  (+864000, +250%)
  x LegacyAlarmTopic  AWS::SNS::Topic  arn:aws:sns:us-east-1:123456789012:web-prod-legacy-alarms  DELETED
  ~ WebSecurityGroup  AWS::EC2::SecurityGroup  sg-0a1b2c3d4e5f60718  MODIFIED
      + /SecurityGroupIngress/1  added {"CidrIp":"0.0.0.0/0","FromPort":22,"IpProtocol":"tcp","ToPort":22}

2 stacks checked, 1 drifted, 4 drifted resources
```

The exit status is `1` because drift was found. The Lambda function's console-added tag is counted as `ignored` because of the rule in `examples/ignore.txt`.

## Getting the input

```bash
aws cloudformation detect-stack-drift --stack-name web-prod
# wait until describe-stack-drift-detection-status reports DETECTION_COMPLETE, then:
aws cloudformation describe-stack-resource-drifts --stack-name web-prod > drifts/web-prod.json
cfn-drift-report drifts/
```

Each file may be the API/CLI response (`{"StackResourceDrifts": [...]}`), a bare list of `StackResourceDrift` objects, or a list of saved pages. Records are grouped by `StackId`, so the stack name comes from the stack ARN (falling back to the file name), and pages saved as separate files for the same stack are merged.

## Usage

```text
cfn-drift-report [PATH ...] [options]
cfn-drift-report --detect STACK [STACK ...] [options]
```

| Option | Meaning |
|---|---|
| `PATH` | JSON file, directory of `*.json` files, or `-` for stdin |
| `-f, --format text\|markdown\|json` | Output format (default `text`) |
| `-o, --output FILE` | Write the report to a file |
| `--all` | Also list `IN_SYNC`, `NOT_CHECKED` and fully ignored resources |
| `--ignore RULE` | Ignore differences, repeatable: `PATH_GLOB` or `RESOURCE_TYPE PATH_GLOB` |
| `--ignore-file FILE` | One rule per line, `#` comments allowed |
| `--max-value N` | Truncate long property values (default 100 characters) |
| `--no-fail` | Exit 0 even when drift is found |
| `--detect STACK ...` | Live mode, see below |
| `--region`, `--profile` | AWS session settings for live mode |
| `--timeout S`, `--interval S` | How long to wait for each detection (default 600 s) and how often to poll (default 5 s) |
| `--save-dir DIR` | Save the fetched drift records as JSON so they can be re-read offline |

Exit status: `0` no drift, `1` drift found, `2` bad input, API error or usage error.

### How the report reads

- Resource markers: `~` modified, `x` deleted, `?` unknown (detection could not run; `DriftStatusReason` is shown), `-` all differences ignored, `=` in sync (with `--all`).
- Property markers follow CloudFormation's `DifferenceType`: `~ NOT_EQUAL` shows expected `->` actual, `+ ADD` shows the value added to a list, `- REMOVE` shows the expected value of the removed property.
- `PropertyPath` is shown as CloudFormation returns it (a JSON pointer such as `/Tags/1`). Values are decoded from their JSON strings; when both sides are numbers the absolute and percentage change are added.
- A `MODIFIED` resource whose every difference matches an ignore rule is reported as `ignored` and does not count as drift. `UNKNOWN` resources are listed but do not count as drift either.

### Ignore rules

```text
# any resource type
/Tags/*
# one resource type (globs work in the type too)
AWS::Lambda::Function /Tags/*
AWS::EC2::* /SecurityGroupIngress/*
```

Globs are shell-style (`fnmatch`), case-sensitive, and `*` also matches `/`.

### Markdown for pull requests or tickets

```bash
cfn-drift-report examples/drifts/web-prod.json --ignore-file examples/ignore.txt -f markdown
```

```markdown
# CloudFormation drift report

| Stack | Status | Resources |
|---|---|---|
| web-prod | **DRIFTED** | 3 modified, 1 deleted, 1 ignored, 2 in sync |

## web-prod

| Resource | Type | Status | Difference |
|---|---|---|---|
| `AssetsBucket` (acme-web-prod-assets) | AWS::S3::Bucket | MODIFIED | NOT_EQUAL: `/VersioningConfiguration/Status  "Enabled" -> "Suspended"` |
| | | | ADD: `/Tags/1  added {"Key":"cost-center","Value":"cc-1042"}` |
| `JobsQueue` (https://sqs.us-east-1.amazonaws.com/123456789012/web-prod-jobs) | AWS::SQS::Queue | MODIFIED | NOT_EQUAL: `/DelaySeconds  20 -> 120  (+100, +500%)` |
| | | | NOT_EQUAL: `/MessageRetentionPeriod  345600 -> 1209600  (+864000, +250%)` |
| `LegacyAlarmTopic` (arn:aws:sns:us-east-1:123456789012:web-prod-legacy-alarms) | AWS::SNS::Topic | DELETED |  |
| `WebSecurityGroup` (sg-0a1b2c3d4e5f60718) | AWS::EC2::SecurityGroup | MODIFIED | ADD: `/SecurityGroupIngress/1  added {"CidrIp":"0.0.0.0/0","FromPort":22,"IpProtocol":"tcp","ToPort":22}` |
```

`-f json` gives the same data in machine-readable form, including every difference with its `ignored` flag and a numeric `delta` where it applies.

## Live mode (`--detect`)

```bash
cfn-drift-report --detect web-prod data-prod --region us-east-1 --save-dir drifts/
```

For each stack this calls `DetectStackDrift`, polls `DescribeStackDriftDetectionStatus` until the operation leaves `DETECTION_IN_PROGRESS`, then reads every page of `DescribeStackResourceDrifts`. If detection ends in `DETECTION_FAILED`, a warning is printed and the results CloudFormation did produce are still reported.

**What this does to your account:** drift detection does not modify stacks or resources. It does start a drift detection operation, which shows up in CloudTrail and in the stack's drift status in the console. CloudFormation reads every supported resource in the stack using your credentials, so you need read permission for each resource type in the stack, not just CloudFormation permissions. Nested stacks are not included; run detection on them by name.

### Required permissions (live mode only)

- `cloudformation:DetectStackDrift`
- `cloudformation:DescribeStackDriftDetectionStatus`
- `cloudformation:DescribeStackResourceDrifts`
- `cloudformation:DetectStackResourceDrift` and `cloudformation:BatchDescribeTypeConfigurations` (listed by AWS as required to detect drift on a stack)
- read permissions for every resource type in the stack, for example `ec2:DescribeInstances` for `AWS::EC2::Instance`, `sqs:GetQueueAttributes` for `AWS::SQS::Queue`

The offline mode needs no AWS access at all.

## Features

- [x] Read `describe-stack-resource-drifts` JSON from a file, a directory of stacks, or stdin
- [x] Per-resource compact diff of `PropertyDifferences` (ADD / REMOVE / NOT_EQUAL) with numeric change
- [x] Ignore lists for known-noisy properties, scoped by resource type
- [x] Text, Markdown and JSON output
- [x] Exit code when drift is found
- [x] Live `--detect` mode (detect, poll, paginate) with `--save-dir`, via an injectable boto3 client
- [ ] Detect drift for every stack in a region (`ListStacks`) in one run
- [ ] Show the full expected/actual property documents side by side
- [ ] StackSet drift

## Limitations

- The report only knows what CloudFormation reports. AWS documents known false positives (for example service defaults that appear in property arrays) and properties it cannot check; use ignore rules for those.
- Live mode has been tested with botocore's Stubber against the documented API shapes, not against a real account.
- Stacks are detected one after another, not in parallel.
- Ignore rules match `PropertyPath` strings; array indices (such as `/Tags/1`) shift when lists change, so prefer globs like `/Tags/*`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Contributing

Issues and pull requests are welcome. Please include a test with any change, and if you add support for a new input shape, add a small fictional fixture to `examples/` or `tests/`.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
