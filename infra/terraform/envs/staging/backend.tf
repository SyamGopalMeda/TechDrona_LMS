# Remote state: S3 in td-shared (bucket td-tfstate, KMS td-tfstate) with DynamoDB locking
# (deployment-and-operations §7). PLACEHOLDERS — the state bucket does not exist yet.
# Init with:  terraform init -backend-config=backend.hcl   (backend.hcl is not committed if it
# carries account ids; see backend.hcl.example)
terraform {
  backend "s3" {
    key     = "techdrona/staging/terraform.tfstate"
    region  = "ap-south-1"
    encrypt = true
    # bucket         = "td-tfstate-<td-shared-account-id>"
    # dynamodb_table = "td-tfstate-lock"
    # kms_key_id     = "alias/td-tfstate"
    # role_arn       = "arn:aws:iam::<td-shared-account-id>:role/td-terraform-state"
  }
}
