# Github Publish Pipeline Service
This pipeline will be deployed into EKS/AWS environment
and will push contents from vocbench for public releases on github.

## Configuration

### GitHub App permissions
The custom Github App could be configured for the organization account. It not needs to be installed on Any account.
The following Repository permissions are required:
- Metadata: Read-only
- Contents: Read and write
- Pull requests: Read and write

The Github App should contain a single installation authorized with all the lexic repositories.

### Required EKS secrets
The following secrets are required and should be configured into EKS environment, and used into `controlled-vocabularies` namespace:
- `LEXIC_CONTROLLED_VOCABULARIES_GITHUB_APP_ID` will contain the Github App ID
- `LEXIC_CONTROLLED_VOCABULARIES_GITHUB_APP_PRIVATE_KEY` will contain the text content of the private key, without -----BEGIN/END------