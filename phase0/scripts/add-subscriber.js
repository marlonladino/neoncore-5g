// Test subscriber matching UERANSIM's default open5gs-ue.yaml credentials.
// IMSI = MCC(999) + MNC(70) + MSISDN(0000000001) = 999700000000001
db = db.getSiblingDB('open5gs');
db.subscribers.deleteMany({ imsi: "999700000000001" });
db.subscribers.insertOne({
  schema_version: 1,
  imsi: "999700000000001",
  msisdn: [],
  imeisv: [],
  mme_host: [],
  mm_realm: [],
  purge_flag: [],
  slice: [
    {
      sst: 1,
      sd: "000001",
      default_indicator: true,
      session: [
        {
          name: "internet",
          type: 3,
          qos: {
            index: 9,
            arp: { priority_level: 8, pre_emption_capability: 1, pre_emption_vulnerability: 2 }
          },
          ambr: {
            downlink: { value: 1000000000, unit: 0 },
            uplink: { value: 1000000000, unit: 0 }
          },
          pcc_rule: []
        }
      ]
    }
  ],
  security: {
    k: "465B5CE8B199B49FAA5F0A2EE238A6BC",
    op: null,
    opc: "E8ED289DEBA952E4283B54E88E6183CA",
    amf: "8000"
  },
  ambr: {
    downlink: { value: 1000000000, unit: 0 },
    uplink: { value: 1000000000, unit: 0 }
  },
  access_restriction_data: 32,
  network_access_mode: 0,
  subscriber_status: 0,
  operator_determined_barring: 0,
  subscribed_rau_tau_timer: 12,
  __v: 0
});
print("Subscriber 999700000000001 provisioned.");
