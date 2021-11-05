# cfn-drift-report

Turn AWS CloudFormation drift results into a readable report: which resources drifted, what changed, and by how much.

## Planned scope

Offline: read describe-stack-resource-drifts JSON (and a directory of them for many stacks), show per resource the property differences (Expected vs Actual, DifferenceType ADD/REMOVE/NOT_EQUAL) as a compact diff, ignore lists for known-noisy properties, Markdown/JSON output, exit code when drift. Live mode (behind --detect): call detect_stack_drift, poll describe_stack_drift_detection_status, then describe_stack_resource_drifts, via injectable client tested with Stubber. README must say plainly that drift detection does not modify stacks but does start a detection operation and needs the read permissions of every resource type.
