class Invoice < ApplicationRecord
  default_scope { where(deleted: false) }
  belongs_to :account
  after_save :notify_customer

  def notify_customer
    InvoiceMailer.issued(self).deliver_now
    update_attribute(:sent_at, Time.now)
  end
end
