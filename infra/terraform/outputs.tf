# Outputs are split per concern across outputs-<concern>.tf files so that
# CD-N PRs adding new outputs don't collide on a single file. See
# outputs-network.tf, outputs-eks.tf, outputs-kms.tf, outputs-s3.tf,
# outputs-iam-irsa.tf.
