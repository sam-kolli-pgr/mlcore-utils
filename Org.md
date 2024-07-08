# Build a container Image
Involves calling the `containerbuild` end point with some spcific inputs

1. an interaface that represents the stratos input
2. a blackldoge + other config class to give the values that the above interface can be instantiates with
3. call the api with the interface in the first step

# Deploying the Pipeline and associated functionality

Involves creating 3 ArgoCD applications (per current design). Creating an argocd application involves calling a collection of stratos endpoints with specific inputs

# Design

Given that there are some common data elements involved in calling the stratos functionality, we shud have an object that can represent one source of truth that can then supply data to the various end points involved, while making sure that the data supplied to each endpoint is exactly correlated with other endpoints(where necesary)

This common object requires varius config, properties, constants etc from "Stratos", Blacklodge Pipeline, AWS accounts/buckets/ecr and SPlunk. then this common "object" can be tested to make sure that the data it provides is correct and if changes had to made, we can make with less propblems. then this common "object" can be tested to make sure that the data it provides is correct and if changes had to made, we can make with less propblems

From blacklodge perspective, the interface providing the functinlaity should provide methods to
1. register/store any data in datastores such as a database, etcd etc
2. build a container image
3. deploy an image in k8s cluster


On Stratos Side:
1. acc:w
