// Viewer request on the S3 behavior. The Next.js static export writes /home/index.html,
// and an S3 REST origin has no index documents, so map /home/ and /home to that file.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.split("/").pop().indexOf(".") === -1) {
    request.uri = uri + "/index.html";
  }
  return request;
}
