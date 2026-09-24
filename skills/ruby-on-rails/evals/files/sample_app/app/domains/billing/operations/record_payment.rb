module Billing
  class RecordPayment
    def self.call(...) = new(...).call

    def initialize(invoice:, amount_cents:)
      @invoice = invoice
      @amount_cents = amount_cents
    end

    def call
      @invoice.payments.create!(amount_cents: @amount_cents)
    end
  end
end
