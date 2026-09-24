class InvoicePublisherService
  def initialize(invoice) = @invoice = invoice
  def call
    @invoice.update!(status: "sent")
  end
end
