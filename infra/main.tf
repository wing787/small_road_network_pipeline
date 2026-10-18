provider "aws" {
  region              = "ap-northeast-1"
  allowed_account_ids = ["754640391511"] # 文字列のリスト

  # このプロバイダで作るものすべてに、自動でタグを付ける
  default_tags {
    tags = {
      Project   = "small-road-network-pipeline"
      ManagedBy = "terraform"
    }
  }
}

resource "aws_s3_bucket" "terraform_lab" {
  bucket = "small-road-network-pipeline-bytf-k8m2"
}
