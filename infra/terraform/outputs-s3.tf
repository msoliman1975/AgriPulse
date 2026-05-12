output "s3_buckets" {
  description = "Bucket names by logical role."
  value = {
    imagery_raw  = aws_s3_bucket.this["imagery_raw"].bucket
    imagery_cogs = aws_s3_bucket.this["imagery_cogs"].bucket
    exports      = aws_s3_bucket.this["exports"].bucket
  }
}
