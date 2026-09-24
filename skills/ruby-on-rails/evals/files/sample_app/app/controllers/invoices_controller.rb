class InvoicesController < ApplicationController
  def index
    @invoices = Invoice.all
  end

  def show
    @invoice = Invoice.find(params[:id])
  end

  def publish
    @invoice = Invoice.find(params[:id])
    InvoicePublisherService.new(@invoice).call
    redirect_to @invoice
  rescue Exception => e
    redirect_to @invoice, alert: e.message
  end

  def create
    @invoice = Invoice.new(params.require(:invoice).permit(:number, :customer_id))
    @invoice.save
    redirect_to @invoice
  end

  private
    def load_stuff
      Time.now
    end
end
