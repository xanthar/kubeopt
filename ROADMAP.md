# Roadmap

This document outlines planned features and improvements for KubeOpt AI.

## Status Legend

- **Planned** - Feature is designed and prioritized
- **In Progress** - Active development
- **Completed** - Released in current version

---

## Near-term (Next Release)

### Recommendation History and Tracking
Track the lifecycle of recommendations from creation to application, including savings realized calculations.

### Namespace-Level Budgets
Set spending limits per namespace with configurable alerts when thresholds are exceeded.

### Rightsizing Confidence Scoring
ML-based confidence scores for recommendations based on historical outcomes and workload patterns.

### Spot Instance Recommendations
Analyze workloads to identify candidates suitable for spot/preemptible instances with potential savings calculations.

---

## Medium-term

### Network Cost Attribution
Attribute network costs (egress, cross-AZ traffic) to specific workloads for complete cost visibility.

### Carbon Footprint Estimation
Calculate and display carbon emissions based on cloud region energy mix with carbon-aware scheduling recommendations.

### Web Dashboard
React-based dashboard with:
- Cost overview and trends visualization
- Optimization run management
- Anomaly timeline
- Cluster management UI
- Recommendation review workflow
- Budget monitoring

---

## Future

### GitOps Integration
Native integration with Flux and ArgoCD for automated PR creation with recommended changes to GitOps repositories.

### Custom Metric Sources
Support additional metrics backends:
- Datadog
- New Relic
- AWS CloudWatch

### Plugin System
Extensible architecture for custom:
- Analyzers
- Cost models
- Notification channels

### Secrets Management Integration
Native support for external secret managers:
- HashiCorp Vault
- AWS Secrets Manager
- Azure Key Vault

### Backup and Disaster Recovery
Automated database backups with:
- S3/GCS storage
- Retention policies
- Point-in-time recovery

---

## How to Contribute

We welcome contributions! If you're interested in working on any of these features:

1. Check the [CONTRIBUTING.md](CONTRIBUTING.md) guide
2. Open an issue to discuss your approach
3. Submit a pull request

Feature requests and ideas are also welcome via GitHub issues.

---

## Version History

See [CHANGELOG.md](CHANGELOG.md) for released features.
