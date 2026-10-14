// Viewer request on the /api/* behavior. The API's routes start at /v1 and /sandbox,
// so /api/v1/me reaches the ALB as /v1/me.
function handler(event) {
  var request = event.request;
  request.uri = request.uri.replace(/^\/api(?=\/|$)/, "") || "/";
  return request;
}
