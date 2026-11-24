@Marker module demo.core {
    requires transitive static example;
    exports demo.api to client.one, client.two;
    opens demo.internal;
    uses demo.api.Service;
    provides demo.api.Service with demo.internal.First, demo.internal.Second;
}
