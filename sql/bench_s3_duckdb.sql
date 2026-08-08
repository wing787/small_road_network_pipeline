INSTALL httpfs; LOAD httpfs;

CREATE SECRET s3_secret (
    TYPE S3,
    PROVIDER 'credential_chain',
    REGION 'ap-northeast-1'
);

CALL enable_logging('HTTP');
SELECT count(*)
FROM read_parquet('s3://small-road-network-pipeline-r7k3/roads/roads_all.parquet');